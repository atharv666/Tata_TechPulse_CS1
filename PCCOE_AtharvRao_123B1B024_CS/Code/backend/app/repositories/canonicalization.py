"""Project-scoped persistence operations for conservative entity canonicalization."""

from uuid import UUID

from sqlalchemy import func, select, update

from app.models.schema import Entity, EntityAlias, EntityEvidence, Relationship
from app.repositories.base import ProjectScopedRepository


class CanonicalizationRepository(ProjectScopedRepository):
    def entities_for_type(self, entity_type: str) -> list[Entity]:
        return list(
            self.session.scalars(
                select(Entity).where(
                    Entity.project_id == self.project_id, Entity.entity_type == entity_type
                )
            )
        )

    def alias_for(self, normalized_alias: str) -> EntityAlias | None:
        return self.session.scalar(
            select(EntityAlias).where(
                EntityAlias.project_id == self.project_id,
                EntityAlias.normalized_alias == normalized_alias,
            )
        )

    def trigram_candidates(
        self, entity_type: str, raw_name: str, minimum_similarity: float = 0.3
    ) -> list[Entity]:
        """Use pg_trgm only to generate candidates; deterministic thresholds still decide."""
        statement = (
            select(Entity)
            .where(
                Entity.project_id == self.project_id,
                Entity.entity_type == entity_type,
                func.similarity(Entity.canonical_name, raw_name) >= minimum_similarity,
            )
            .order_by(func.similarity(Entity.canonical_name, raw_name).desc())
        )
        return list(self.session.scalars(statement))

    def merge_into(
        self, canonical_id: UUID, duplicate_id: UUID, alias: str, normalized_alias: str
    ) -> None:
        """Preserve evidence and relationship references before deleting an untrusted duplicate."""
        canonical = self.session.scalar(
            select(Entity).where(Entity.project_id == self.project_id, Entity.id == canonical_id)
        )
        duplicate = self.session.scalar(
            select(Entity).where(Entity.project_id == self.project_id, Entity.id == duplicate_id)
        )
        if canonical is None or duplicate is None or canonical.entity_type != duplicate.entity_type:
            raise ValueError("Canonical merge requires same-project entities of the same type.")
        self.session.execute(
            update(Relationship)
            .where(
                Relationship.project_id == self.project_id,
                Relationship.source_entity_id == duplicate_id,
            )
            .values(source_entity_id=canonical_id)
        )
        self.session.execute(
            update(Relationship)
            .where(
                Relationship.project_id == self.project_id,
                Relationship.target_entity_id == duplicate_id,
            )
            .values(target_entity_id=canonical_id)
        )
        self.session.execute(
            update(EntityEvidence)
            .where(
                EntityEvidence.project_id == self.project_id,
                EntityEvidence.entity_id == duplicate_id,
            )
            .values(entity_id=canonical_id)
        )
        existing_alias = self.alias_for(normalized_alias)
        if existing_alias is None:
            self.session.add(
                EntityAlias(
                    project_id=self.project_id,
                    entity_id=canonical_id,
                    alias=alias,
                    normalized_alias=normalized_alias,
                )
            )
        self.session.delete(duplicate)
