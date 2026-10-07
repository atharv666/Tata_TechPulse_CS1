"""Project-scoped persistence for review history, provenance, and audit events."""

from uuid import UUID

from sqlalchemy import select

from app.models.enums import TrustState, ValidationState
from app.models.schema import (
    AuditEvent,
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
    Section,
    ValidationEvent,
)
from app.repositories.base import ProjectScopedRepository


class ReviewRepository(ProjectScopedRepository):
    """Persists only facts and events that belong to the repository project."""

    def pending_entities(self) -> list[Entity]:
        return list(
            self.session.scalars(
                select(Entity).where(
                    Entity.project_id == self.project_id,
                    Entity.trust_state == TrustState.CANDIDATE,
                    Entity.validation_state == ValidationState.PENDING,
                )
            )
        )

    def pending_relationships(self) -> list[Relationship]:
        return list(
            self.session.scalars(
                select(Relationship).where(
                    Relationship.project_id == self.project_id,
                    Relationship.trust_state == TrustState.CANDIDATE,
                    Relationship.validation_state == ValidationState.PENDING,
                )
            )
        )

    def get_entity(self, entity_id: UUID) -> Entity | None:
        return self.session.scalar(
            select(Entity).where(Entity.project_id == self.project_id, Entity.id == entity_id)
        )

    def get_relationship(self, relationship_id: UUID) -> Relationship | None:
        return self.session.scalar(
            select(Relationship).where(
                Relationship.project_id == self.project_id, Relationship.id == relationship_id
            )
        )

    def add_entity(self, entity: Entity) -> Entity:
        self._require_project(entity.project_id)
        self.session.add(entity)
        return entity

    def add_relationship(self, relationship: Relationship) -> Relationship:
        self._require_project(relationship.project_id)
        self.session.add(relationship)
        return relationship

    def entity_evidence(self, entity_id: UUID) -> list[EntityEvidence]:
        return list(
            self.session.scalars(
                select(EntityEvidence).where(
                    EntityEvidence.project_id == self.project_id,
                    EntityEvidence.entity_id == entity_id,
                )
            )
        )

    def relationship_evidence(self, relationship_id: UUID) -> list[RelationshipEvidence]:
        return list(
            self.session.scalars(
                select(RelationshipEvidence).where(
                    RelationshipEvidence.project_id == self.project_id,
                    RelationshipEvidence.relationship_id == relationship_id,
                )
            )
        )

    def entity_provenance(
        self, entity_id: UUID
    ) -> list[tuple[EntityEvidence, Chunk, Section, DocumentVersion, Document]]:
        statement = (
            select(EntityEvidence, Chunk, Section, DocumentVersion, Document)
            .join(Chunk, Chunk.id == EntityEvidence.chunk_id)
            .join(Section, Section.id == Chunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                EntityEvidence.project_id == self.project_id, EntityEvidence.entity_id == entity_id
            )
        )
        return list(self.session.execute(statement).tuples())

    def relationship_provenance(
        self, relationship_id: UUID
    ) -> list[tuple[RelationshipEvidence, Chunk, Section, DocumentVersion, Document]]:
        statement = (
            select(RelationshipEvidence, Chunk, Section, DocumentVersion, Document)
            .join(Chunk, Chunk.id == RelationshipEvidence.chunk_id)
            .join(Section, Section.id == Chunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                RelationshipEvidence.project_id == self.project_id,
                RelationshipEvidence.relationship_id == relationship_id,
            )
        )
        return list(self.session.execute(statement).tuples())

    def validation_history(
        self, entity_id: UUID | None = None, relationship_id: UUID | None = None
    ) -> list[ValidationEvent]:
        if (entity_id is None) == (relationship_id is None):
            raise ValueError("Provide exactly one review fact identifier.")
        statement = select(ValidationEvent).where(ValidationEvent.project_id == self.project_id)
        if entity_id is not None:
            statement = statement.where(ValidationEvent.entity_id == entity_id)
        else:
            statement = statement.where(ValidationEvent.relationship_id == relationship_id)
        return list(self.session.scalars(statement.order_by(ValidationEvent.created_at)))

    def record_validation(self, event: ValidationEvent) -> ValidationEvent:
        self._require_project(event.project_id)
        self.session.add(event)
        return event

    def record_audit(self, event: AuditEvent) -> AuditEvent:
        self._require_project(event.project_id)
        self.session.add(event)
        return event

    def audit_history(self, resource_id: UUID | None = None) -> list[AuditEvent]:
        statement = select(AuditEvent).where(AuditEvent.project_id == self.project_id)
        if resource_id is not None:
            statement = statement.where(AuditEvent.resource_id == resource_id)
        return list(self.session.scalars(statement.order_by(AuditEvent.created_at)))

    def _require_project(self, resource_project_id: UUID) -> None:
        if resource_project_id != self.project_id:
            raise ValueError("Resource project_id does not match repository project scope.")
