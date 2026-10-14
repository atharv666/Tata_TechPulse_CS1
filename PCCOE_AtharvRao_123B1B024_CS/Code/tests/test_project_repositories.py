"""Repository invariant tests independent of a database server."""

from uuid import uuid4

import pytest
from app.models.enums import ExtractionType
from app.models.schema import Document, Entity
from app.repositories.documents import DocumentRepository
from app.repositories.graph import GraphRepository


def test_document_repository_rejects_cross_project_resource() -> None:
    repository = DocumentRepository(session=None, project_id=uuid4())  # type: ignore[arg-type]
    document = Document(
        project_id=uuid4(),
        name="HLD",
        media_type="application/pdf",
        storage_uri="private://hld.pdf",
        created_by="developer",
    )

    with pytest.raises(ValueError, match="project_id"):
        repository.add_document(document)


def test_graph_repository_rejects_cross_project_entity() -> None:
    repository = GraphRepository(session=None, project_id=uuid4())  # type: ignore[arg-type]
    entity = Entity(
        project_id=uuid4(),
        canonical_name="BrakeController",
        normalized_name="brakecontroller",
        entity_type="SOFTWARE_COMPONENT",
        extraction_type=ExtractionType.EXPLICIT,
        confidence="0.900",
    )

    with pytest.raises(ValueError, match="project_id"):
        repository.add_entity(entity)
