"""Read models and reviewer actions for the knowledge graph (project-scoped)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import ProjectAccess
from app.canonicalization.merge import undo_merge
from app.core.errors import ConflictError, NotFoundError
from app.graph.facts import GraphFactLoader
from app.graph.traversal import GraphTraversal, TraversalSpec
from app.models.enums import MembershipRole, ValidationState
from app.models.schema import (
    AuditEvent,
    Entity,
    EntityAlias,
    EntityMerge,
    Finding,
    Relationship,
)
from app.repositories.review import ReviewRepository
from app.schemas.graph import (
    AliasDisplay,
    EndpointDisplay,
    EntityDetail,
    EntityNode,
    EntityReport,
    FindingResponse,
    MergedEntityDisplay,
    MergeResponse,
    RelatedItem,
    RelationshipDetail,
)
from app.services.review import ReviewActor, ReviewService

_REVIEW_ROLES = frozenset({MembershipRole.REVIEWER, MembershipRole.ADMIN})


def active_entity_filter(project_id: UUID) -> list[ColumnElement[bool]]:
    """Entities that are live: not merged into another and not replaced by a correction."""
    return [
        Entity.project_id == project_id,
        Entity.merged_into_id.is_(None),
        Entity.superseded_by_id.is_(None),
    ]


def active_relationship_filter(project_id: UUID) -> list[ColumnElement[bool]]:
    return [
        Relationship.project_id == project_id,
        Relationship.superseded_by_id.is_(None),
        ~Relationship.attributes.has_key("inactive_reason"),
    ]


class KnowledgeService:
    def __init__(self, session: Session, access: ProjectAccess) -> None:
        self._session = session
        self._access = access
        self._review = ReviewService(
            ReviewRepository(session, access.project_id),
            ReviewActor(access.user_id, access.project_id, access.role),
        )

    # -- listings ----------------------------------------------------------------------------
    def entities(
        self,
        offset: int,
        limit: int,
        *,
        entity_type: str | None = None,
        validation_state: str | None = None,
        query: str | None = None,
    ) -> tuple[list[Entity], int]:
        conditions = active_entity_filter(self._access.project_id)
        if entity_type:
            conditions.append(Entity.entity_type == entity_type)
        if validation_state:
            conditions.append(Entity.validation_state == ValidationState(validation_state))
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            alias_match = select(EntityAlias.entity_id).where(
                EntityAlias.project_id == self._access.project_id,
                EntityAlias.alias.ilike(pattern),
            )
            conditions.append(or_(Entity.canonical_name.ilike(pattern), Entity.id.in_(alias_match)))
        statement = select(Entity).where(*conditions).order_by(Entity.canonical_name, Entity.id)
        total = int(
            self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), total

    def relationships(
        self,
        offset: int,
        limit: int,
        *,
        relationship_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> tuple[list[Relationship], int]:
        conditions = active_relationship_filter(self._access.project_id)
        if relationship_type:
            conditions.append(Relationship.relationship_type == relationship_type)
        if entity_id:
            conditions.append(
                or_(
                    Relationship.source_entity_id == entity_id,
                    Relationship.target_entity_id == entity_id,
                )
            )
        statement = (
            select(Relationship)
            .where(*conditions)
            .order_by(Relationship.created_at, Relationship.id)
        )
        total = int(
            self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), total

    # -- detail --------------------------------------------------------------------------------
    def entity_detail(self, entity_id: UUID) -> EntityDetail:
        entity = self._session.scalar(
            select(Entity).where(
                Entity.project_id == self._access.project_id, Entity.id == entity_id
            )
        )
        if entity is None:
            raise NotFoundError("ENTITY_NOT_FOUND", "Entity was not found in this project.")
        aliases = self._session.scalars(
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity.id)
            .order_by(EntityAlias.alias)
        )
        merged_rows = self._session.execute(
            select(EntityMerge, Entity)
            .join(Entity, Entity.id == EntityMerge.merged_entity_id)
            .where(
                EntityMerge.canonical_entity_id == entity.id,
                EntityMerge.undone_at.is_(None),
            )
            .order_by(EntityMerge.created_at)
        ).tuples()
        relationship_count = self._session.scalar(
            select(func.count(Relationship.id)).where(
                *active_relationship_filter(self._access.project_id),
                or_(
                    Relationship.source_entity_id == entity.id,
                    Relationship.target_entity_id == entity.id,
                ),
            )
        )
        findings = self._session.scalars(
            select(Finding)
            .where(Finding.project_id == self._access.project_id, Finding.entity_id == entity.id)
            .order_by(Finding.created_at)
        )
        return EntityDetail(
            id=entity.id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            confidence=entity.confidence,
            raw_confidence=entity.raw_confidence,
            extraction_type=entity.extraction_type.value,
            validation_state=entity.validation_state.value,
            trust_state=entity.trust_state.value,
            merged_into_id=entity.merged_into_id,
            superseded_by_id=entity.superseded_by_id,
            aliases=[AliasDisplay(alias=a.alias, source=a.source) for a in aliases],
            merged_entities=[
                MergedEntityDisplay(
                    merge_id=merge.id,
                    entity_id=other.id,
                    name=other.canonical_name,
                    decided_by=merge.decided_by,
                    similarity=merge.similarity,
                    reason=merge.reason,
                    created_at=merge.created_at,
                )
                for merge, other in merged_rows
            ],
            evidence=self._review.entity_provenance(entity.id),
            history=self._review.entity_validation_history(entity.id),
            relationship_count=int(relationship_count or 0),
            findings=[_finding(item) for item in findings],
        )

    def relationship_detail(self, relationship_id: UUID) -> RelationshipDetail:
        relationship = self._session.scalar(
            select(Relationship).where(
                Relationship.project_id == self._access.project_id,
                Relationship.id == relationship_id,
            )
        )
        if relationship is None:
            raise NotFoundError(
                "RELATIONSHIP_NOT_FOUND", "Relationship was not found in this project."
            )
        source = self._session.get(Entity, relationship.source_entity_id)
        target = self._session.get(Entity, relationship.target_entity_id)
        if source is None or target is None:
            raise NotFoundError("ENTITY_NOT_FOUND", "A relationship endpoint is missing.")
        findings = self._session.scalars(
            select(Finding)
            .where(
                Finding.project_id == self._access.project_id,
                Finding.relationship_id == relationship.id,
            )
            .order_by(Finding.created_at)
        )
        return RelationshipDetail(
            id=relationship.id,
            source_entity_id=relationship.source_entity_id,
            target_entity_id=relationship.target_entity_id,
            relationship_type=relationship.relationship_type,
            confidence=relationship.confidence,
            raw_confidence=relationship.raw_confidence,
            extraction_type=relationship.extraction_type.value,
            validation_state=relationship.validation_state.value,
            trust_state=relationship.trust_state.value,
            superseded_by_id=relationship.superseded_by_id,
            source=EndpointDisplay(
                id=source.id, name=source.canonical_name, entity_type=source.entity_type
            ),
            target=EndpointDisplay(
                id=target.id, name=target.canonical_name, entity_type=target.entity_type
            ),
            evidence=self._review.relationship_provenance(relationship.id),
            history=self._review.relationship_validation_history(relationship.id),
            findings=[_finding(item) for item in findings],
        )

    # -- one-page report -----------------------------------------------------------------------
    def entity_report(self, entity_id: UUID) -> EntityReport:
        """Everything the graph states about an entity, grouped by relationship type."""
        entity = self._session.scalar(
            select(Entity).where(
                *active_entity_filter(self._access.project_id), Entity.id == entity_id
            )
        )
        if entity is None:
            raise NotFoundError("ENTITY_NOT_FOUND", "No live entity with this id in the project.")
        traversal = GraphTraversal(self._session, self._access.project_id).traverse(
            TraversalSpec.both(entity.id, depth=1, edge_limit=500)
        )
        facts = GraphFactLoader(self._session, self._access.project_id).load(traversal.edges)
        outgoing: dict[str, list[RelatedItem]] = {}
        incoming: dict[str, list[RelatedItem]] = {}
        for fact in sorted(facts, key=lambda item: (item.relationship_type, item.statement)):
            outward = fact.source_id == entity.id
            other_id, other_name, other_type = (
                (fact.target_id, fact.target_name, fact.target_type)
                if outward
                else (fact.source_id, fact.source_name, fact.source_type)
            )
            first = fact.citations[0] if fact.citations else None
            item = RelatedItem(
                confidence=Decimal(str(fact.confidence)),
                extraction_type=fact.extraction_type,
                validation_state=fact.validation_state,
                relationship_id=fact.relationship_id,
                entity_id=other_id,
                name=other_name,
                entity_type=other_type,
                source_document=first.document_name if first else None,
                source_section=first.section_path or first.section_heading if first else None,
                source_page=first.page_start if first else None,
                source_excerpt=first.excerpt[:400] if first else None,
            )
            (outgoing if outward else incoming).setdefault(fact.relationship_type, []).append(item)
        aliases = self._session.scalars(
            select(EntityAlias.alias)
            .where(EntityAlias.entity_id == entity.id)
            .order_by(EntityAlias.alias)
        )
        findings = self._session.scalars(
            select(Finding)
            .where(
                Finding.project_id == self._access.project_id,
                Finding.entity_id == entity.id,
                Finding.status == "OPEN",
            )
            .order_by(Finding.created_at)
        )
        return EntityReport(
            entity=EntityNode.model_validate(entity, from_attributes=True),
            aliases=list(aliases),
            outgoing=outgoing,
            incoming=incoming,
            findings=[_finding(row) for row in findings],
            evidence=self._review.entity_provenance(entity.id),
        )

    # -- merges --------------------------------------------------------------------------------
    def merges(
        self, offset: int, limit: int, *, include_undone: bool = True
    ) -> tuple[list[MergeResponse], int]:
        conditions = [EntityMerge.project_id == self._access.project_id]
        if not include_undone:
            conditions.append(EntityMerge.undone_at.is_(None))
        base = select(EntityMerge).where(*conditions)
        total = int(self._session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        merges = list(
            self._session.scalars(
                base.order_by(EntityMerge.created_at.desc(), EntityMerge.id)
                .offset(offset)
                .limit(limit)
            )
        )
        names = {
            entity_id: name
            for entity_id, name in self._session.execute(
                select(Entity.id, Entity.canonical_name).where(
                    Entity.id.in_(
                        {m.canonical_entity_id for m in merges}
                        | {m.merged_entity_id for m in merges}
                    )
                )
            )
        }
        return [
            MergeResponse(
                id=m.id,
                canonical_entity_id=m.canonical_entity_id,
                canonical_name=names.get(m.canonical_entity_id, "?"),
                merged_entity_id=m.merged_entity_id,
                merged_name=names.get(m.merged_entity_id, "?"),
                decided_by=m.decided_by,
                rule=m.rule,
                similarity=m.similarity,
                reason=m.reason,
                llm_model=m.llm_model,
                blocking_keys=list(m.blocking_keys),
                created_at=m.created_at,
                undone_at=m.undone_at,
                undone_by=m.undone_by,
            )
            for m in merges
        ], total

    def undo_merge(self, merge_id: UUID, reason: str) -> None:
        if self._access.role not in _REVIEW_ROLES:
            raise PermissionError("Only REVIEWER or ADMIN may undo an entity merge.")
        merge = self._session.scalar(
            select(EntityMerge).where(
                EntityMerge.project_id == self._access.project_id, EntityMerge.id == merge_id
            )
        )
        if merge is None:
            raise NotFoundError("MERGE_NOT_FOUND", "Merge was not found in this project.")
        try:
            undo_merge(self._session, merge, self._access.user_id, reason)
        except ValueError as error:
            raise ConflictError("MERGE_NOT_UNDOABLE", str(error)) from error
        self._session.add(
            AuditEvent(
                project_id=self._access.project_id,
                actor_id=self._access.user_id,
                action="ENTITY_MERGE_UNDONE",
                resource_type="entity",
                resource_id=merge.canonical_entity_id,
                details={"merge_id": str(merge.id), "reason": reason},
            )
        )


def _finding(row: Finding) -> FindingResponse:
    return FindingResponse(
        id=row.id,
        finding_type=row.finding_type,
        severity=row.severity,
        status=row.status,
        summary=row.summary,
        details=row.details,
        entity_id=row.entity_id,
        relationship_id=row.relationship_id,
        confidence=row.confidence,
        detected_by=row.detected_by,
        dismissed_by=row.dismissed_by,
        dismissed_reason=row.dismissed_reason,
        created_at=row.created_at,
    )


def finding_response(row: Finding) -> FindingResponse:
    return _finding(row)
