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

    def pending_chunks(
        self,
        model: str,
        model_version: str,
        limit: int,
        *,
        document_version_id: object = None,
        after_id: object = None,
    ) -> list[Chunk]:
        pending = [
            chunk
            for chunk in sorted(self.chunks, key=lambda item: item.id)
            if chunk.embedding is None
            or chunk.embedding_model != model
            or chunk.embedding_model_version != model_version
        ]
        if after_id is not None:
            pending = [chunk for chunk in pending if chunk.id > after_id]  # type: ignore[operator]
        return pending[:limit]

    def reusable_embeddings(
        self, content_hashes: list[str], model: str, model_version: str
    ) -> dict[str, list[float]]:
        return {
            chunk.content_hash: list(chunk.embedding)
            for chunk in self.chunks
            if chunk.content_hash in content_hashes
            and chunk.embedding is not None
            and chunk.embedding_model == model
            and chunk.embedding_model_version == model_version
        }

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


class NeverUpdatesRepository(InMemoryVectorRepository):
    """Simulates a store whose writes are not visible to the next 'pending' query."""

    def pending_chunks(self, *args: object, **kwargs: object) -> list[Chunk]:
        return super().pending_chunks(*args, **kwargs)  # type: ignore[arg-type]

    def store_embedding(
        self, chunk: Chunk, vector: list[float], model: str, model_version: str
    ) -> None:
        self.stored = (
            getattr(self, "stored", 0) + 1
        )  # deliberately does NOT touch the chunk


def test_indexing_terminates_even_if_stored_vectors_are_not_visible_to_the_next_query() -> (
    None
):
    """Regression: with autoflush off the old 're-select pending' loop never ended (unbounded calls)."""
    provider = FakeEmbeddingProvider(3)
    repository = NeverUpdatesRepository([make_chunk(str(index)) for index in range(7)])
    service = EmbeddingService(provider, settings())

    result = run(service.index_pending(repository, batch_size=3))

    assert result.indexed_count == 7  # type: ignore[union-attr]
    assert [len(request) for request in provider.requests] == [3, 3, 1]


def test_after_batch_callback_reports_cumulative_progress() -> None:
    repository = InMemoryVectorRepository(
        [make_chunk(str(index)) for index in range(5)]
    )
    progress: list[tuple[int, int]] = []
    service = EmbeddingService(FakeEmbeddingProvider(3), settings())

    run(
        service.index_pending(
            repository, batch_size=2, after_batch=lambda t, n: progress.append((t, n))
        )
    )

    assert progress == [(2, 2), (4, 2), (5, 1)]


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


def test_identical_text_reuses_an_existing_vector_instead_of_calling_the_provider() -> (
    None
):
    provider = FakeEmbeddingProvider(3, lambda text: [float(len(text)), 0.0, 1.0])
    done = make_chunk("unchanged section")
    done.content_hash = "h-unchanged"
    done.embedding = [9.0, 9.0, 9.0]
    done.embedding_model, done.embedding_model_version = "fake-embedding", "v1"
    same = make_chunk("unchanged section")  # e.g. the same section in a new revision
    same.content_hash = "h-unchanged"
    new = make_chunk("brand new section")
    new.content_hash = "h-new"
    repository = InMemoryVectorRepository([done, same, new])
    service = EmbeddingService(provider, settings())

    result = run(service.index_pending(repository))

    assert result.indexed_count == 2 and result.reused_count == 1  # type: ignore[union-attr]
    assert provider.requests == [["brand new section"]]  # one provider call, one text
    assert same.embedding == [9.0, 9.0, 9.0] and new.embedding is not None


def test_duplicate_text_inside_one_batch_is_embedded_once() -> None:
    provider = FakeEmbeddingProvider(3)
    first, second = make_chunk("repeated"), make_chunk("repeated")
    first.content_hash = second.content_hash = "h-repeat"
    repository = InMemoryVectorRepository([first, second])

    run(EmbeddingService(provider, settings()).index_pending(repository))

    assert provider.requests == [["repeated"]]
    assert first.embedding == second.embedding
