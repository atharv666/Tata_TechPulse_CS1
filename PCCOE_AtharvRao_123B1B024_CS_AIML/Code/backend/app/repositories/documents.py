"""Project-scoped document hierarchy persistence."""

from uuid import UUID

from sqlalchemy import select

from app.models.schema import Chunk, Document, DocumentVersion, Section
from app.repositories.base import ProjectScopedRepository


class DocumentRepository(ProjectScopedRepository):
    def add_document(self, document: Document) -> Document:
        self._require_project(document.project_id)
        self.session.add(document)
        return document

    def get_document(self, document_id: UUID) -> Document | None:
        statement = select(Document).where(
            Document.project_id == self.project_id, Document.id == document_id
        )
        return self.session.scalar(statement)

    def add_version(self, version: DocumentVersion) -> DocumentVersion:
        self._require_project(version.project_id)
        self.session.add(version)
        return version

    def add_section(self, section: Section) -> Section:
        self._require_project(section.project_id)
        self.session.add(section)
        return section

    def add_chunk(self, chunk: Chunk) -> Chunk:
        self._require_project(chunk.project_id)
        self.session.add(chunk)
        return chunk

    def chunks_for_version(self, version_id: UUID) -> list[Chunk]:
        return list(
            self.session.scalars(
                select(Chunk).where(
                    Chunk.project_id == self.project_id, Chunk.document_version_id == version_id
                )
            )
        )

    def _require_project(self, resource_project_id: UUID) -> None:
        if resource_project_id != self.project_id:
            raise ValueError("Resource project_id does not match repository project scope.")
