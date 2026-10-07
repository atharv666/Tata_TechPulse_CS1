"""Explicit transactional graph build; queries never invoke this module."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonicalization.core import canonical_relationship_type
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.enums import JobState, TrustState, ValidationState
from app.models.schema import (
    Entity,
    EntityEvidence,
    Job,
    Relationship,
    RelationshipEvidence,
    ValidationEvent,
)
from app.validation.graph import interface_findings, validate_entity, validate_relationship


@dataclass(frozen=True)
class GraphBuildResult:
    job_id: UUID
    validated_entities: int
    validated_relationships: int
    rejected_entities: int
    rejected_relationships: int
    findings: tuple[str, ...]


class GraphBuildService:
    """Validates candidate knowledge under an explicit job and records immutable outcomes."""

    def build(
        self, session: Session, project_id: UUID, actor_id: str, job: Job | None = None
    ) -> GraphBuildResult:
        """Perform an explicit atomic build transaction; no automatic trust promotion occurs."""
        transaction = nullcontext() if session.in_transaction() else session.begin()
        with transaction:
            if job is None:
                job = Job(
                    project_id=project_id,
                    job_type="GRAPH_BUILD",
                    state=JobState.RUNNING,
                    requested_by=actor_id,
                    details={},
                )
                session.add(job)
                session.flush()
            entities = list(
                session.scalars(
                    select(Entity).where(
                        Entity.project_id == project_id,
                        Entity.validation_state == ValidationState.PENDING,
                    )
                )
            )
            relationships = list(
                session.scalars(
                    select(Relationship).where(
                        Relationship.project_id == project_id,
                        Relationship.validation_state == ValidationState.PENDING,
                    )
                )
            )
            rejected_entities = sum(
                self._validate_entity(session, project_id, actor_id, entity) for entity in entities
            )
            rejected_relationships = sum(
                self._validate_relationship(session, project_id, actor_id, relationship)
                for relationship in relationships
            )
            all_project_entities = list(
                session.scalars(select(Entity).where(Entity.project_id == project_id))
            )
            all_project_relationships = list(
                session.scalars(select(Relationship).where(Relationship.project_id == project_id))
            )
            findings = interface_findings(all_project_entities, all_project_relationships)
            job.state = JobState.COMPLETED
            job.details = {
                "rejected_entities": rejected_entities,
                "rejected_relationships": rejected_relationships,
                "findings": findings,
            }
            metrics.increment("graph_builds_completed")
            metrics.increment("graph_build_validated_entities", len(entities))
            metrics.increment("graph_build_validated_relationships", len(relationships))
            get_logger(__name__).info(
                "graph_build_completed",
                extra={"project_id": project_id, "build_id": job.id},
            )
            return GraphBuildResult(
                job.id,
                len(entities),
                len(relationships),
                rejected_entities,
                rejected_relationships,
                tuple(message for messages in findings.values() for message in messages),
            )

    def _validate_entity(
        self, session: Session, project_id: UUID, actor_id: str, entity: Entity
    ) -> int:
        evidence = list(
            session.scalars(
                select(EntityEvidence).where(
                    EntityEvidence.project_id == project_id, EntityEvidence.entity_id == entity.id
                )
            )
        )
        outcome = validate_entity(entity, evidence)
        entity.confidence = outcome.confidence
        if not outcome.valid:
            entity.validation_state = ValidationState.REJECTED
            session.add(
                ValidationEvent(
                    project_id=project_id,
                    entity_id=entity.id,
                    state=ValidationState.REJECTED,
                    actor_id=actor_id,
                    reason="; ".join(outcome.reasons),
                )
            )
            return 1
        entity.trust_state = TrustState.CANDIDATE
        session.add(
            ValidationEvent(
                project_id=project_id,
                entity_id=entity.id,
                state=ValidationState.PENDING,
                actor_id=actor_id,
                reason="Deterministic validation passed; human review remains required.",
            )
        )
        return 0

    def _validate_relationship(
        self, session: Session, project_id: UUID, actor_id: str, relationship: Relationship
    ) -> int:
        source = session.scalar(
            select(Entity).where(
                Entity.project_id == project_id, Entity.id == relationship.source_entity_id
            )
        )
        target = session.scalar(
            select(Entity).where(
                Entity.project_id == project_id, Entity.id == relationship.target_entity_id
            )
        )
        evidence = list(
            session.scalars(
                select(RelationshipEvidence).where(
                    RelationshipEvidence.project_id == project_id,
                    RelationshipEvidence.relationship_id == relationship.id,
                )
            )
        )
        outcome = validate_relationship(relationship, source, target, evidence)
        relationship.confidence = outcome.confidence
        canonical_type = canonical_relationship_type(relationship.relationship_type)
        if canonical_type is not None:
            relationship.relationship_type = canonical_type
        if not outcome.valid:
            relationship.validation_state = ValidationState.REJECTED
            session.add(
                ValidationEvent(
                    project_id=project_id,
                    relationship_id=relationship.id,
                    state=ValidationState.REJECTED,
                    actor_id=actor_id,
                    reason="; ".join(outcome.reasons),
                )
            )
            return 1
        relationship.trust_state = TrustState.CANDIDATE
        session.add(
            ValidationEvent(
                project_id=project_id,
                relationship_id=relationship.id,
                state=ValidationState.PENDING,
                actor_id=actor_id,
                reason="Deterministic validation passed; human review remains required.",
            )
        )
        return 0
