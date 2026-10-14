"""Explicit, idempotent graph build; queries never invoke this module.

A build binds staged relationship candidates to canonical entities, validates what is pending,
refreshes persisted findings, and records the outcome. It can be rerun any number of times: values
are recomputed from immutable inputs (``raw_confidence``, evidence), a validation event is written
only when something changes, and reviewed (human) facts are never touched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonicalization.binding import BindingResult, RelationshipBinder
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.enums import TrustState, ValidationState
from app.models.schema import (
    Entity,
    EntityEvidence,
    Job,
    MergeDecision,
    Relationship,
    RelationshipEvidence,
    ValidationEvent,
)
from app.services.findings import SyncResult, sync_findings
from app.validation.findings import detect_all
from app.validation.graph import validate_entity, validate_relationship

PASSED = "Deterministic validation passed; human review remains required."


@dataclass(frozen=True)
class GraphBuildResult:
    job_id: UUID
    validated_entities: int
    validated_relationships: int
    rejected_entities: int
    rejected_relationships: int
    candidates_total: int
    candidates_bound: int
    candidates_unbound: int
    relationships_created: int
    findings_opened: int
    findings_reopened: int
    findings_resolved: int
    findings_open: int

    def as_details(self) -> dict[str, int]:
        details = asdict(self)
        details.pop("job_id")
        return {key: int(value) for key, value in details.items()}


class GraphBuildService:
    """Binds, validates and records candidate knowledge; it never promotes anything to trusted."""

    def build(
        self, session: Session, project_id: UUID, actor_id: str, job: Job | None = None
    ) -> GraphBuildResult:
        """Run inside the caller's transaction. ``job`` only receives the outcome record."""
        binding = RelationshipBinder().bind(session, project_id)
        entities, rejected_entities = self._validate_entities(session, project_id, actor_id)
        relationships, rejected_relationships = self._validate_relationships(
            session, project_id, actor_id
        )
        findings = self._refresh_findings(session, project_id, binding)
        result = GraphBuildResult(
            job.id if job is not None else project_id,
            entities,
            relationships,
            rejected_entities,
            rejected_relationships,
            binding.candidates,
            binding.bound,
            binding.unbound,
            binding.relationships_created,
            findings.opened,
            findings.reopened,
            findings.resolved,
            findings.open_total,
        )
        if job is not None:
            details = dict(job.details)
            details["build"] = result.as_details()
            job.details = details
        metrics.increment("graph_builds_completed")
        get_logger(__name__).info(
            "graph_build_completed",
            extra={"project_id": project_id, "build_id": job.id if job else None},
        )
        return result

    # -- entities ----------------------------------------------------------------------------
    def _validate_entities(
        self, session: Session, project_id: UUID, actor_id: str
    ) -> tuple[int, int]:
        entities = list(
            session.scalars(
                select(Entity)
                .where(
                    Entity.project_id == project_id,
                    Entity.validation_state == ValidationState.PENDING,
                    Entity.merged_into_id.is_(None),
                    Entity.superseded_by_id.is_(None),
                )
                .order_by(Entity.created_at, Entity.id)
            )
        )
        has_event = set(
            session.scalars(
                select(ValidationEvent.entity_id).where(
                    ValidationEvent.project_id == project_id,
                    ValidationEvent.entity_id.is_not(None),
                )
            )
        )
        rejected = 0
        for entity in entities:
            evidence = list(
                session.scalars(
                    select(EntityEvidence).where(
                        EntityEvidence.project_id == project_id,
                        EntityEvidence.entity_id == entity.id,
                    )
                )
            )
            outcome = validate_entity(entity, evidence)
            self._set_confidence(entity, outcome.confidence)
            if not outcome.valid:
                entity.validation_state = ValidationState.REJECTED
                self._event(
                    session,
                    project_id,
                    actor_id,
                    ValidationState.REJECTED,
                    "; ".join(outcome.reasons),
                    entity_id=entity.id,
                )
                rejected += 1
            elif entity.id not in has_event:
                self._event(
                    session,
                    project_id,
                    actor_id,
                    ValidationState.PENDING,
                    PASSED,
                    entity_id=entity.id,
                )
            entity.trust_state = TrustState.CANDIDATE
        return len(entities), rejected

    # -- relationships -----------------------------------------------------------------------
    def _validate_relationships(
        self, session: Session, project_id: UUID, actor_id: str
    ) -> tuple[int, int]:
        relationships = [
            item
            for item in session.scalars(
                select(Relationship)
                .where(
                    Relationship.project_id == project_id,
                    Relationship.validation_state == ValidationState.PENDING,
                    Relationship.superseded_by_id.is_(None),
                )
                .order_by(Relationship.created_at, Relationship.id)
            )
            if "inactive_reason" not in item.attributes
        ]
        has_event = set(
            session.scalars(
                select(ValidationEvent.relationship_id).where(
                    ValidationEvent.project_id == project_id,
                    ValidationEvent.relationship_id.is_not(None),
                )
            )
        )
        rejected = 0
        for relationship in relationships:
            source = session.get(Entity, relationship.source_entity_id)
            target = session.get(Entity, relationship.target_entity_id)
            evidence = list(
                session.scalars(
                    select(RelationshipEvidence).where(
                        RelationshipEvidence.project_id == project_id,
                        RelationshipEvidence.relationship_id == relationship.id,
                    )
                )
            )
            outcome = validate_relationship(relationship, source, target, evidence)
            self._set_confidence(relationship, outcome.confidence)
            if not outcome.valid:
                relationship.validation_state = ValidationState.REJECTED
                self._event(
                    session,
                    project_id,
                    actor_id,
                    ValidationState.REJECTED,
                    "; ".join(outcome.reasons),
                    relationship_id=relationship.id,
                )
                rejected += 1
            elif relationship.id not in has_event:
                self._event(
                    session,
                    project_id,
                    actor_id,
                    ValidationState.PENDING,
                    PASSED,
                    relationship_id=relationship.id,
                )
            relationship.trust_state = TrustState.CANDIDATE
        return len(relationships), rejected

    # -- findings ----------------------------------------------------------------------------
    @staticmethod
    def _refresh_findings(session: Session, project_id: UUID, binding: BindingResult) -> SyncResult:
        session.flush()
        entities = list(session.scalars(select(Entity).where(Entity.project_id == project_id)))
        relationships = list(
            session.scalars(select(Relationship).where(Relationship.project_id == project_id))
        )
        decisions = list(
            session.scalars(
                select(MergeDecision).where(
                    MergeDecision.project_id == project_id, MergeDecision.decision == "UNSURE"
                )
            )
        )
        drafts = detect_all(entities, relationships, decisions, binding.problems)
        return sync_findings(session, project_id, drafts)

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _set_confidence(fact: Entity | Relationship, confidence: Decimal) -> None:
        if fact.confidence != confidence:
            fact.confidence = confidence

    @staticmethod
    def _event(
        session: Session,
        project_id: UUID,
        actor_id: str,
        state: ValidationState,
        reason: str,
        *,
        entity_id: UUID | None = None,
        relationship_id: UUID | None = None,
    ) -> None:
        session.add(
            ValidationEvent(
                project_id=project_id,
                entity_id=entity_id,
                relationship_id=relationship_id,
                state=state,
                actor_id=actor_id,
                reason=reason,
            )
        )
