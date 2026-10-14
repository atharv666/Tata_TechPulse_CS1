"""Embedding/indexing services and the plain vector retrieval used by the graph layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.config import EmbeddingProviderSettings
from app.models.schema import Chunk
from app.providers.contracts import EmbeddingProvider, StructuredOutputError
from app.repositories.vectors import VectorRepository, VectorSearchHit


@dataclass(frozen=True)
class IndexingResult:
    indexed_count: int
    model: str
    model_version: str
    reused_count: int = 0
    provider_texts: int = 0


def _key(chunk: Chunk) -> str:
    """Identity of the text to embed: its hash, or the chunk id when it has no hash."""
    return chunk.content_hash or f"id:{chunk.id}"


class EmbeddingService:
    """Uses the provider contract only; vectors are validated before persistence."""

    def __init__(self, provider: EmbeddingProvider, settings: EmbeddingProviderSettings) -> None:
        if settings.model is None:
            raise ValueError("Embedding model is required for indexing and retrieval.")
        self._provider = provider
        self._settings = settings
        self._model = settings.model

    async def index_pending(
        self,
        repository: VectorRepository,
        batch_size: int = 32,
        *,
        document_version_id: UUID | None = None,
        after_batch: Callable[[int, int], None] | None = None,
    ) -> IndexingResult:
        """Embed every chunk that lacks a vector of the configured identity.

        * The scan advances by primary key (keyset pagination) instead of re-running "what is
          still pending?" against state that may not have been flushed, so it always terminates
          after at most ``ceil(n / batch_size) + 1`` queries.
        * The embedded text is the chunk's ``embedding_text`` (breadcrumb + raw content). Chunks
          whose text hash already has a vector (unchanged sections of a new revision, repeated
          sections) copy it instead of calling the provider again.
        * ``after_batch(total_so_far, batch_len)`` lets a job commit each batch, which makes
          progress durable and keeps provider calls out of one giant transaction.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        total = reused = provider_texts = 0
        last_id: UUID | None = None
        while True:
            chunks = repository.pending_chunks(
                self._model,
                self._settings.model_version,
                batch_size,
                document_version_id=document_version_id,
                after_id=last_id,
            )
            if not chunks:
                break
            last_id = chunks[-1].id
            vectors = repository.reusable_embeddings(
                [chunk.content_hash for chunk in chunks if chunk.content_hash],
                self._model,
                self._settings.model_version,
            )
            reused_here = sum(1 for chunk in chunks if _key(chunk) in vectors)
            needed: dict[str, Chunk] = {}
            for chunk in chunks:
                if _key(chunk) not in vectors:
                    needed.setdefault(_key(chunk), chunk)
            if needed:
                keys = list(needed)
                result = await self._provider.embed_documents(
                    [needed[key].embedding_text for key in keys]
                )
                self._validate_result(result.vectors, result.model, result.dimensions, len(keys))
                vectors.update(zip(keys, result.vectors, strict=True))
                provider_texts += len(keys)
            for chunk in chunks:
                repository.store_embedding(
                    chunk, vectors[_key(chunk)], self._model, self._settings.model_version
                )
            total += len(chunks)
            reused += reused_here
            if after_batch is not None:
                after_batch(total, len(chunks))
        return IndexingResult(
            total, self._model, self._settings.model_version, reused, provider_texts
        )

    async def reembed(self, repository: VectorRepository, batch_size: int = 32) -> IndexingResult:
        """Explicitly re-index chunks whose persisted identity differs from configuration."""
        return await self.index_pending(repository, batch_size)

    async def embed_query(self, query: str) -> list[float]:
        if not query.strip():
            raise ValueError("Query text cannot be empty.")
        result = await self._provider.embed_query(query)
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
