"""Human review actions that preserve candidates and record immutable history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.canonicalization.core import normalize_name
from app.core.errors import ConflictError, NotFoundError
from app.core.metrics import metrics
from app.extraction.taxonomy import ENTITY_TYPES, RELATIONSHIP_TYPES
from app.models.enums import MembershipRole, TrustState, ValidationState
from app.models.schema import (
    Entity,
    EntityAlias,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
    ValidationEvent,
)
from app.repositories.review import ReviewRepository
from app.schemas.review import (
    AuditEventDisplay,
    ProvenanceDisplay,
    ReviewQueueItem,
    ValidationHistoryItem,
)
from app.services.audit import AuditEventService


class ReviewPermissionError(PermissionError):
    """Raised when a project member attempts an action outside their assigned role."""


@dataclass(frozen=True)
class ReviewActor:
    user_id: str
    project_id: UUID
    role: MembershipRole


class ReviewService:
    """Applies reviewer decisions without allowing them to overwrite AI candidate facts."""

    _REVIEW_ROLES = frozenset({MembershipRole.REVIEWER, MembershipRole.ADMIN})

    def __init__(self, repository: ReviewRepository, actor: ReviewActor) -> None:
        if repository.project_id != actor.project_id:
            raise ReviewPermissionError("Reviewer membership is not scoped to this project.")
        self._repository = repository
        self._actor = actor
        self._audit = AuditEventService(repository, actor.user_id)

    def review_queue(self) -> list[ReviewQueueItem]:
        self._require_read()
        entities = self._repository.pending_entities()
        relationships = self._repository.pending_relationships()
        names = self._repository.entity_names(
            {item.source_entity_id for item in relationships}
            | {item.target_entity_id for item in relationships}
        )
        return [
            *[
                ReviewQueueItem(
                    fact_kind="ENTITY",
                    fact_id=entity.id,
                    label=f"{entity.canonical_name} [{entity.entity_type}]",
                    confidence=entity.confidence,
                    extraction_type=entity.extraction_type,
                    validation_state=entity.validation_state,
                    provenance=self.entity_provenance(entity.id),
                )
                for entity in entities
            ],
            *[
                ReviewQueueItem(
                    fact_kind="RELATIONSHIP",
                    fact_id=relationship.id,
                    label=(
                        f"{names.get(relationship.source_entity_id, '?')} "
                        f"{relationship.relationship_type} "
                        f"{names.get(relationship.target_entity_id, '?')}"
                    ),
                    confidence=relationship.confidence,
                    extraction_type=relationship.extraction_type,
                    validation_state=relationship.validation_state,
                    provenance=self.relationship_provenance(relationship.id),
                )
                for relationship in relationships
            ],
        ]

    def verify_entity(self, entity_id: UUID, reason: str | None = None) -> Entity:
        self._require_reviewer()
        entity = self._entity_for_review(entity_id)
        entity.trust_state = TrustState.TRUSTED
        entity.validation_state = ValidationState.HUMAN_VERIFIED
        self._record(entity=entity, state=ValidationState.HUMAN_VERIFIED, reason=reason)
        metrics.record_review_decision("VERIFIED")
        return entity

    def verify_relationship(self, relationship_id: UUID, reason: str | None = None) -> Relationship:
        self._require_reviewer()
        relationship = self._relationship_for_review(relationship_id)
        relationship.trust_state = TrustState.TRUSTED
        relationship.validation_state = ValidationState.HUMAN_VERIFIED
        self._record(relationship=relationship, state=ValidationState.HUMAN_VERIFIED, reason=reason)
        metrics.record_review_decision("VERIFIED")
        return relationship

    def reject_entity(self, entity_id: UUID, reason: str) -> Entity:
        self._require_reviewer()
        entity = self._entity_for_review(entity_id)
        entity.trust_state = TrustState.CANDIDATE
        entity.validation_state = ValidationState.REJECTED
        self._record(entity=entity, state=ValidationState.REJECTED, reason=reason)
        metrics.record_review_decision("REJECTED")
        return entity

    def reject_relationship(self, relationship_id: UUID, reason: str) -> Relationship:
        self._require_reviewer()
        relationship = self._relationship_for_review(relationship_id)
        relationship.trust_state = TrustState.CANDIDATE
        relationship.validation_state = ValidationState.REJECTED
        self._record(relationship=relationship, state=ValidationState.REJECTED, reason=reason)
        metrics.record_review_decision("REJECTED")
        return relationship

    def correct_entity(
        self, entity_id: UUID, canonical_name: str, entity_type: str, reason: str
    ) -> Entity:
        """Replace an entity with a reviewed one; the original stays, superseded, for audit.

        Relationships of the original move to the corrected entity (as clones of the edges, so
        the originals remain), and the old name becomes an alias so later statements that still
        use it resolve to the corrected entity.
        """
        self._require_reviewer()
        original = self._entity_for_review(entity_id)
        name = canonical_name.strip()
        normalized = normalize_name(name)
        if not normalized:
            raise ValueError("The corrected entity needs a name.")
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unsupported entity type '{entity_type}'.")
        if normalized == original.normalized_name and entity_type == original.entity_type:
            raise ValueError("The correction changes nothing; verify the entity instead.")
        if self._repository.find_entity(normalized, entity_type) is not None:
            raise ConflictError(
                "ENTITY_ALREADY_EXISTS",
                f"An entity named '{name}' of type {entity_type} already exists. "
                "Reject this candidate or merge the duplicates instead.",
            )
        corrected = Entity(
            id=uuid4(),
            project_id=original.project_id,
            canonical_name=name,
            normalized_name=normalized,
            entity_type=entity_type,
            trust_state=TrustState.TRUSTED,
            extraction_type=original.extraction_type,
            validation_state=ValidationState.HUMAN_CORRECTED,
            raw_confidence=original.raw_confidence,
            confidence=original.confidence,
            extraction_metadata={
                **original.extraction_metadata,
                "corrected_from_entity_id": str(original.id),
                "reviewer_id": self._actor.user_id,
            },
        )
        self._repository.add_entity(corrected)
        self._repository.session.flush()
        self._clone_entity_evidence(original, corrected)
        self._carry_over_aliases(original, corrected)
        self._move_relationships(original, corrected)
        original.validation_state = ValidationState.HUMAN_CORRECTED
        original.trust_state = TrustState.CANDIDATE
        original.superseded_by_id = corrected.id
        self._record(entity=original, state=ValidationState.HUMAN_CORRECTED, reason=reason)
        self._record(entity=corrected, state=ValidationState.HUMAN_CORRECTED, reason=reason)
        metrics.increment("review_corrections")
        metrics.record_review_decision("CORRECTED")
        return corrected

    def correct_relationship(
        self,
        relationship_id: UUID,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relationship_type: str,
        reason: str,
    ) -> Relationship:
        self._require_reviewer()
        original = self._relationship_for_review(relationship_id)
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"Unsupported relationship type '{relationship_type}'.")
        if source_entity_id == target_entity_id:
            raise ValueError("A relationship needs two different endpoints.")
        for endpoint_id in (source_entity_id, target_entity_id):
            self._require_active_endpoint(endpoint_id)
        if (
            source_entity_id == original.source_entity_id
            and target_entity_id == original.target_entity_id
            and relationship_type == original.relationship_type
        ):
            raise ValueError("The correction changes nothing; verify the relationship instead.")
        twin = self._repository.find_active_relationship(
            source_entity_id, target_entity_id, relationship_type
        )
        if twin is not None:
            raise ConflictError(
                "RELATIONSHIP_ALREADY_EXISTS",
                "This relationship already exists. Reject the candidate instead of correcting it.",
            )
        corrected = Relationship(
            id=uuid4(),
            project_id=original.project_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relationship_type=relationship_type,
            trust_state=TrustState.TRUSTED,
            extraction_type=original.extraction_type,
            validation_state=ValidationState.HUMAN_CORRECTED,
            raw_confidence=original.raw_confidence,
            confidence=original.confidence,
            attributes={
                **original.attributes,
                "corrected_from_relationship_id": str(original.id),
                "reviewer_id": self._actor.user_id,
            },
        )
        self._repository.add_relationship(corrected)
        self._repository.session.flush()
        self._clone_relationship_evidence(original, corrected)
        original.validation_state = ValidationState.HUMAN_CORRECTED
        original.trust_state = TrustState.CANDIDATE
        original.superseded_by_id = corrected.id
        self._record(relationship=original, state=ValidationState.HUMAN_CORRECTED, reason=reason)
        self._record(relationship=corrected, state=ValidationState.HUMAN_CORRECTED, reason=reason)
        metrics.increment("review_corrections")
        metrics.record_review_decision("CORRECTED")
        return corrected

    def _require_active_endpoint(self, entity_id: UUID) -> None:
        endpoint = self._repository.get_entity(entity_id)
        if endpoint is None:
            raise NotFoundError(
                "ENTITY_NOT_FOUND", f"Entity {entity_id} was not found in this project."
            )
        if (
            endpoint.merged_into_id is not None
            or endpoint.superseded_by_id is not None
            or endpoint.validation_state is ValidationState.REJECTED
        ):
            raise ConflictError(
                "ENTITY_NOT_ACTIVE",
                f"'{endpoint.canonical_name}' is merged, replaced or rejected and cannot be an "
                "endpoint.",
            )

    def entity_provenance(self, entity_id: UUID) -> list[ProvenanceDisplay]:
        self._require_read()
        return [
            self._provenance_display(*row) for row in self._repository.entity_provenance(entity_id)
        ]

    def relationship_provenance(self, relationship_id: UUID) -> list[ProvenanceDisplay]:
        self._require_read()
        return [
            self._provenance_display(*row)
            for row in self._repository.relationship_provenance(relationship_id)
        ]

    def entity_validation_history(self, entity_id: UUID) -> list[ValidationHistoryItem]:
        self._require_read()
        return self._validation_history(entity_id=entity_id)

    def relationship_validation_history(self, relationship_id: UUID) -> list[ValidationHistoryItem]:
        self._require_read()
        return self._validation_history(relationship_id=relationship_id)

    def audit_history(self, resource_id: UUID | None = None) -> list[AuditEventDisplay]:
        self._require_read()
        return self._audit.history(resource_id)

    def _record(
        self,
        state: ValidationState,
        reason: str | None,
        entity: Entity | None = None,
        relationship: Relationship | None = None,
    ) -> None:
        if (entity is None) == (relationship is None):
            raise ValueError("A review event must target exactly one fact.")
        resource: Entity | Relationship = entity if entity is not None else relationship  # type: ignore[assignment]
        self._repository.record_validation(
            ValidationEvent(
                project_id=self._actor.project_id,
                entity_id=entity.id if entity is not None else None,
                relationship_id=relationship.id if relationship is not None else None,
                state=state,
                actor_id=self._actor.user_id,
                reason=reason,
            )
        )
        self._audit.record(
            action=f"REVIEW_{state}",
            resource_type="ENTITY" if entity is not None else "RELATIONSHIP",
            resource_id=resource.id,
            details={"validation_state": state.value, "reason": reason},
        )

    def _validation_history(
        self, entity_id: UUID | None = None, relationship_id: UUID | None = None
    ) -> list[ValidationHistoryItem]:
        return [
            ValidationHistoryItem(
                state=event.state,
                actor_id=event.actor_id,
                reason=event.reason,
                created_at=event.created_at,
            )
            for event in self._repository.validation_history(entity_id, relationship_id)
        ]

    def _entity_for_review(self, entity_id: UUID) -> Entity:
        entity = self._repository.get_entity(entity_id)
        if entity is None:
            raise NotFoundError("ENTITY_NOT_FOUND", "Entity was not found in this project.")
        if (
            entity.validation_state is not ValidationState.PENDING
            or entity.merged_into_id is not None
            or entity.superseded_by_id is not None
        ):
            raise ConflictError(
                "NOT_PENDING",
                "This entity was already reviewed, merged into another entity or replaced.",
            )
        return entity

    def _relationship_for_review(self, relationship_id: UUID) -> Relationship:
        relationship = self._repository.get_relationship(relationship_id)
        if relationship is None:
            raise NotFoundError(
                "RELATIONSHIP_NOT_FOUND", "Relationship was not found in this project."
            )
        if (
            relationship.validation_state is not ValidationState.PENDING
            or relationship.superseded_by_id is not None
        ):
            raise ConflictError(
                "NOT_PENDING", "This relationship was already reviewed or replaced."
            )
        return relationship

    def _carry_over_aliases(self, original: Entity, corrected: Entity) -> None:
        """The corrected entity answers to everything the original did, including its old name."""
        for alias in self._repository.aliases_of(original.id):
            alias.entity_id = corrected.id
        old_name = original.normalized_name
        if old_name != corrected.normalized_name and self._repository.alias_owner(old_name) is None:
            self._repository.add_alias(
                EntityAlias(
                    project_id=original.project_id,
                    entity_id=corrected.id,
                    alias=original.canonical_name,
                    normalized_alias=old_name,
                    source="HUMAN",
                )
            )

    def _move_relationships(self, original: Entity, corrected: Entity) -> None:
        """Re-attach the original's edges to the corrected entity without altering the originals."""
        for relationship in self._repository.active_relationships_touching(original.id):
            source = relationship.source_entity_id
            target = relationship.target_entity_id
            source = corrected.id if source == original.id else source
            target = corrected.id if target == original.id else target
            if source == target:
                continue  # would be a self-loop; the edge stays on the superseded entity
            twin = self._repository.find_active_relationship(
                source, target, relationship.relationship_type
            )
            if twin is not None:
                relationship.superseded_by_id = twin.id
                continue
            clone = Relationship(
                id=uuid4(),
                project_id=relationship.project_id,
                source_entity_id=source,
                target_entity_id=target,
                relationship_type=relationship.relationship_type,
                trust_state=relationship.trust_state,
                extraction_type=relationship.extraction_type,
                validation_state=relationship.validation_state,
                raw_confidence=relationship.raw_confidence,
                confidence=relationship.confidence,
                attributes={
                    **relationship.attributes,
                    "moved_from_relationship_id": str(relationship.id),
                },
            )
            self._repository.add_relationship(clone)
            self._repository.session.flush()
            self._clone_relationship_evidence(relationship, clone)
            relationship.superseded_by_id = clone.id

    def _require_read(self) -> None:
        if self._actor.role not in set(MembershipRole):
            raise ReviewPermissionError("Unknown project membership role.")

    def _require_reviewer(self) -> None:
        self._require_read()
        if self._actor.role not in self._REVIEW_ROLES:
            raise ReviewPermissionError("Only REVIEWER or ADMIN may review candidate facts.")

    @staticmethod
    def _provenance_display(
        evidence: EntityEvidence | RelationshipEvidence,
        chunk: Any,
        section: Any,
        version: Any,
        document: Any,
    ) -> ProvenanceDisplay:
        return ProvenanceDisplay(
            chunk_id=chunk.id,
            document_id=document.id,
            document_version_id=version.id,
            document_name=document.name,
            section_heading=section.heading,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            source_classification=evidence.source_classification,
            excerpt=evidence.excerpt,
            start_offset=evidence.start_offset,
            end_offset=evidence.end_offset,
        )

    def _clone_entity_evidence(self, original: Entity, corrected: Entity) -> None:
        for evidence in self._repository.entity_evidence(original.id):
            self._repository.session.add(
                EntityEvidence(
                    project_id=original.project_id,
                    entity_id=corrected.id,
                    chunk_id=evidence.chunk_id,
                    source_classification=evidence.source_classification,
                    excerpt=evidence.excerpt,
                    start_offset=evidence.start_offset,
                    end_offset=evidence.end_offset,
                )
            )

    def _clone_relationship_evidence(self, original: Relationship, corrected: Relationship) -> None:
        for evidence in self._repository.relationship_evidence(original.id):
            self._repository.session.add(
                RelationshipEvidence(
                    project_id=original.project_id,
                    relationship_id=corrected.id,
                    chunk_id=evidence.chunk_id,
                    source_classification=evidence.source_classification,
                    excerpt=evidence.excerpt,
                    start_offset=evidence.start_offset,
                    end_offset=evidence.end_offset,
                )
            )
