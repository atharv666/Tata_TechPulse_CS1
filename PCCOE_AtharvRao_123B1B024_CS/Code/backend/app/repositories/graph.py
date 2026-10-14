"""Project-scoped entity, directed relationship, and provenance persistence."""

from uuid import UUID

from sqlalchemy import select

from app.models.schema import (
    Entity,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
    ValidationEvent,
)
from app.repositories.base import ProjectScopedRepository


class GraphRepository(ProjectScopedRepository):
    def add_entity(self, entity: Entity) -> Entity:
        self._require_project(entity.project_id)
        self.session.add(entity)
        return entity

    def get_entity(self, entity_id: UUID) -> Entity | None:
        statement = select(Entity).where(
            Entity.project_id == self.project_id, Entity.id == entity_id
        )
        return self.session.scalar(statement)

    def add_relationship(self, relationship: Relationship) -> Relationship:
        self._require_project(relationship.project_id)
        source = self.get_entity(relationship.source_entity_id)
        target = self.get_entity(relationship.target_entity_id)
        if source is None or target is None:
            raise ValueError("Relationship endpoints must exist in the same project.")
        self.session.add(relationship)
        return relationship

    def outgoing_relationships(self, entity_id: UUID) -> list[Relationship]:
        statement = select(Relationship).where(
            Relationship.project_id == self.project_id, Relationship.source_entity_id == entity_id
        )
        return list(self.session.scalars(statement))

    def add_entity_evidence(self, evidence: EntityEvidence) -> EntityEvidence:
        self._require_project(evidence.project_id)
        self._require_entity(evidence.entity_id)
        self.session.add(evidence)
        return evidence

    def add_relationship_evidence(self, evidence: RelationshipEvidence) -> RelationshipEvidence:
        self._require_project(evidence.project_id)
        relationship = self.session.scalar(
            self.within_project(Relationship).where(Relationship.id == evidence.relationship_id)
        )
        if relationship is None:
            raise ValueError("Relationship evidence must belong to the same project.")
        self.session.add(evidence)
        return evidence

    def record_validation(self, event: ValidationEvent) -> ValidationEvent:
        self._require_project(event.project_id)
        self.session.add(event)
        return event

    def validations_for_entity(self, entity_id: UUID) -> list[ValidationEvent]:
        statement = select(ValidationEvent).where(
            ValidationEvent.project_id == self.project_id, ValidationEvent.entity_id == entity_id
        )
        return list(self.session.scalars(statement))

    def _require_project(self, resource_project_id: UUID) -> None:
        if resource_project_id != self.project_id:
            raise ValueError("Resource project_id does not match repository project scope.")

    def _require_entity(self, entity_id: UUID) -> None:
        if self.get_entity(entity_id) is None:
            raise ValueError("Entity evidence must belong to an entity in the same project.")
