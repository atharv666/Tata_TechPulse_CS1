"""Deterministic, project-scoped document ingestion and contextual chunking."""

from app.ingestion.service import IngestionService, Upload

__all__ = ["IngestionService", "Upload"]
