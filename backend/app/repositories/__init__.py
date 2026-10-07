"""Project-scoped repositories that preserve isolation and provenance invariants."""

from app.repositories.canonicalization import CanonicalizationRepository
from app.repositories.documents import DocumentRepository
from app.repositories.graph import GraphRepository
from app.repositories.projects import ProjectRepository
from app.repositories.vectors import VectorRepository

__all__ = [
    "CanonicalizationRepository",
    "DocumentRepository",
    "GraphRepository",
    "ProjectRepository",
    "VectorRepository",
]
