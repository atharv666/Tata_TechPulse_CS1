"""Vector-only embedding/indexing services; graph retrieval remains out of scope."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.config import EmbeddingProviderSettings
from app.providers.contracts import EmbeddingProvider, StructuredOutputError
from app.repositories.vectors import VectorRepository, VectorSearchHit


@dataclass(frozen=True)
class IndexingResult:
    indexed_count: int
    model: str
    model_version: str


class EmbeddingService:
    """Uses the provider contract only; vectors are validated before persistence."""

    def __init__(self, provider: EmbeddingProvider, settings: EmbeddingProviderSettings) -> None:
        if settings.model is None:
            raise ValueError("Embedding model is required for indexing and retrieval.")
        self._provider = provider
        self._settings = settings
        self._model = settings.model

    async def index_pending(
        self, repository: VectorRepository, batch_size: int = 32
    ) -> IndexingResult:
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        total = 0
        while chunks := repository.pending_chunks(
            self._model, self._settings.model_version, batch_size
        ):
            result = await self._provider.embed([chunk.content for chunk in chunks])
            self._validate_result(result.vectors, result.model, result.dimensions, len(chunks))
            for chunk, vector in zip(chunks, result.vectors, strict=True):
                repository.store_embedding(chunk, vector, self._model, self._settings.model_version)
            total += len(chunks)
        return IndexingResult(total, self._model, self._settings.model_version)

    async def reembed(self, repository: VectorRepository, batch_size: int = 32) -> IndexingResult:
        """Explicitly re-index chunks whose persisted identity differs from configuration."""
        return await self.index_pending(repository, batch_size)

    async def embed_query(self, query: str) -> list[float]:
        if not query.strip():
            raise ValueError("Query text cannot be empty.")
        result = await self._provider.embed([query])
        self._validate_result(result.vectors, result.model, result.dimensions, 1)
        return result.vectors[0]

    def _validate_result(
        self, vectors: list[list[float]], model: str, dimensions: int, count: int
    ) -> None:
        if model != self._model:
            raise StructuredOutputError(
                "Embedding provider returned a different model than configured."
            )
        if dimensions != self._settings.dimensions or len(vectors) != count:
            raise StructuredOutputError(
                "Embedding provider result does not match configured dimensions or batch size."
            )
        if any(len(vector) != self._settings.dimensions for vector in vectors):
            raise StructuredOutputError("Embedding vector dimensions do not match configuration.")

    @property
    def model_identity(self) -> tuple[str, str]:
        """Return the model/version identity used for both indexing and queries."""
        return self._model, self._settings.model_version


class VectorRetrievalService:
    """Runs project-scoped vector retrieval and returns provenance-ready source metadata."""

    def __init__(self, embeddings: EmbeddingService) -> None:
        self._embeddings = embeddings

    async def search(
        self,
        repository: VectorRepository,
        query: str,
        top_k: int,
        document_version_id: UUID | None = None,
    ) -> list[VectorSearchHit]:
        query_vector = await self._embeddings.embed_query(query)
        model, model_version = self._embeddings.model_identity
        return repository.search(
            query_vector,
            model,
            model_version,
            top_k,
            document_version_id,
        )
