"""Project-scoped pgvector persistence and source-metadata retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.models.schema import Chunk, Document, DocumentVersion, Section
from app.repositories.base import ProjectScopedRepository


@dataclass(frozen=True)
class VectorSearchHit:
    chunk_id: UUID
    document_version_id: UUID
    document_id: UUID
    document_name: str
    section_id: UUID
    section_heading: str
    content: str
    page_start: int | None
    page_end: int | None
    distance: float


class VectorRepository(ProjectScopedRepository):
    """All operations are scoped to exactly one project at construction time."""

    def pending_chunks(self, model: str, model_version: str, limit: int) -> list[Chunk]:
        statement = (
            select(Chunk)
            .where(
                Chunk.project_id == self.project_id,
                (Chunk.embedding.is_(None))
                | (Chunk.embedding_model != model)
                | (Chunk.embedding_model_version != model_version),
            )
            .order_by(Chunk.created_at, Chunk.id)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def store_embedding(
        self, chunk: Chunk, vector: list[float], model: str, model_version: str
    ) -> None:
        if chunk.project_id != self.project_id:
            raise ValueError("Chunk project_id does not match vector repository scope.")
        chunk.embedding = vector
        chunk.embedding_model = model
        chunk.embedding_model_version = model_version
        chunk.embedded_at = datetime.now(UTC)

    def search(
        self,
        query_vector: list[float],
        model: str,
        model_version: str,
        top_k: int,
        document_version_id: UUID | None = None,
    ) -> list[VectorSearchHit]:
        """Search only same-identity vectors inside the repository's project boundary."""
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        distance = Chunk.embedding.cosine_distance(query_vector)
        statement = (
            select(
                Chunk,
                DocumentVersion.document_id,
                Document.name,
                Section.heading,
                distance.label("distance"),
            )
            .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .join(Section, Chunk.section_id == Section.id)
            .where(
                Chunk.project_id == self.project_id,
                Chunk.embedding.is_not(None),
                Chunk.embedding_model == model,
                Chunk.embedding_model_version == model_version,
            )
            .order_by(distance)
            .limit(top_k)
        )
        if document_version_id is not None:
            statement = statement.where(Chunk.document_version_id == document_version_id)
        rows = self.session.execute(statement).all()
        return [
            VectorSearchHit(
                chunk_id=chunk.id,
                document_version_id=chunk.document_version_id,
                document_id=document_id,
                document_name=document_name,
                section_id=chunk.section_id,
                section_heading=section_heading,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                distance=float(hit_distance),
            )
            for chunk, document_id, document_name, section_heading, hit_distance in rows
        ]
