"""Vector indexing/retrieval service tests using only the fake embedding provider."""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.core.config import EmbeddingProviderSettings
from app.models.schema import Chunk
from app.providers.contracts import EmbeddingResult, StructuredOutputError
from app.providers.fake import FakeEmbeddingProvider
from app.retrieval.vector import EmbeddingService, VectorRetrievalService


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


@dataclass
class InMemoryVectorRepository:
    chunks: list[Chunk]
    project_id: object = None
    searches: list[tuple[object, ...]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.searches = []

    def pending_chunks(self, model: str, model_version: str, limit: int) -> list[Chunk]:
        return [
            chunk
            for chunk in self.chunks
            if chunk.embedding is None
            or chunk.embedding_model != model
            or chunk.embedding_model_version != model_version
        ][:limit]

    def store_embedding(
        self, chunk: Chunk, vector: list[float], model: str, model_version: str
    ) -> None:
        chunk.embedding = vector
        chunk.embedding_model = model
        chunk.embedding_model_version = model_version

    def search(self, *args: object) -> list[object]:
        self.searches.append(args)
        return []


def make_chunk(content: str) -> Chunk:
    return Chunk(
        project_id=uuid4(),
        document_version_id=uuid4(),
        section_id=uuid4(),
        ordinal=1,
        content=content,
        token_count=1,
    )


def settings(version: str = "v1") -> EmbeddingProviderSettings:
    return EmbeddingProviderSettings(
        provider="fake", model="fake-embedding", dimensions=3, model_version=version
    )


def test_batch_indexing_persists_model_identity_and_processes_multiple_batches() -> (
    None
):
    provider = FakeEmbeddingProvider(3, lambda text: [float(len(text)), 0.0, 1.0])
    repository = InMemoryVectorRepository(
        [make_chunk("one"), make_chunk("two"), make_chunk("three")]
    )
    service = EmbeddingService(provider, settings())

    result = run(service.index_pending(repository, batch_size=2))

    assert result.indexed_count == 3  # type: ignore[union-attr]
    assert [len(request) for request in provider.requests] == [2, 1]
    assert all(
        chunk.embedding_model == "fake-embedding"
        and chunk.embedding_model_version == "v1"
        for chunk in repository.chunks
    )


def test_query_retrieval_passes_model_version_top_k_and_version_filter() -> None:
    provider = FakeEmbeddingProvider(3)
    service = EmbeddingService(provider, settings())
    retrieval = VectorRetrievalService(service)
    repository = InMemoryVectorRepository([])
    version_id = uuid4()

    result = run(
        retrieval.search(
            repository, "brake interface", top_k=4, document_version_id=version_id
        )
    )

    assert result == []
    assert repository.searches[0][1:5] == ("fake-embedding", "v1", 4, version_id)


def test_model_version_change_requires_explicit_reembedding() -> None:
    chunk = make_chunk("signal")
    chunk.embedding = [0.0, 0.0, 0.0]
    chunk.embedding_model = "fake-embedding"
    chunk.embedding_model_version = "v1"
    repository = InMemoryVectorRepository([chunk])
    service = EmbeddingService(FakeEmbeddingProvider(3), settings("v2"))

    result = run(service.reembed(repository))

    assert result.indexed_count == 1  # type: ignore[union-attr]
    assert chunk.embedding_model_version == "v2"


def test_dimension_mismatch_is_rejected_before_persistence() -> None:
    repository = InMemoryVectorRepository([make_chunk("signal")])
    service = EmbeddingService(FakeEmbeddingProvider(2), settings())

    with pytest.raises(StructuredOutputError, match="dimensions"):
        run(service.index_pending(repository))


class WrongModelProvider(FakeEmbeddingProvider):
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        result = await super().embed(texts)
        return EmbeddingResult(
            vectors=result.vectors, model="other-model", dimensions=result.dimensions
        )


def test_model_change_is_rejected_for_query_and_index_consistency() -> None:
    service = EmbeddingService(WrongModelProvider(3), settings())

    with pytest.raises(StructuredOutputError, match="different model"):
        run(service.embed_query("signal"))


def test_vector_repository_search_statement_always_includes_project_boundary() -> None:
    from app.repositories.vectors import VectorRepository

    class CaptureResult:
        def all(self) -> list[object]:
            return []

    class CaptureSession:
        statement: object | None = None

        def execute(self, statement: object) -> CaptureResult:
            self.statement = statement
            return CaptureResult()

    session = CaptureSession()
    repository = VectorRepository(session=session, project_id=uuid4())  # type: ignore[arg-type]
    assert repository.search([0.0, 0.0, 0.0], "fake-embedding", "v1", top_k=2) == []
    assert session.statement is not None
    assert "chunks.project_id" in str(session.statement)
