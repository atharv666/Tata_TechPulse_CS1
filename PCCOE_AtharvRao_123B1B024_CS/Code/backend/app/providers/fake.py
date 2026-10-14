"""Deterministic in-memory providers used only by tests and local wiring checks."""

from collections.abc import Callable
from typing import Any

from app.providers.contracts import (
    CandidateStructuredOutput,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMRequest,
    StructuredModel,
)

#: Test seams. ``LLM_PROVIDER=fake`` / ``EMBEDDING_PROVIDER=fake`` is the only way to reach
#: these, so production configuration can never select a scripted provider by accident.
_llm_factory: Callable[[], LLMProvider] | None = None
_embedding_factory: Callable[[int], EmbeddingProvider] | None = None


def register_fake_llm(factory: Callable[[], LLMProvider] | None) -> None:
    """Install (or clear, with ``None``) the object returned when ``LLM_PROVIDER=fake``."""
    global _llm_factory
    _llm_factory = factory


def register_fake_embedding(factory: Callable[[int], EmbeddingProvider] | None) -> None:
    """Install (or clear) the factory that receives the configured embedding dimension."""
    global _embedding_factory
    _embedding_factory = factory


def create_fake_llm() -> LLMProvider:
    return _llm_factory() if _llm_factory is not None else FakeLLMProvider(payload={})


def create_fake_embedding(dimensions: int) -> EmbeddingProvider:
    if _embedding_factory is not None:
        return _embedding_factory(dimensions)
    return FakeEmbeddingProvider(dimensions=dimensions)


class FakeLLMProvider(LLMProvider):
    def __init__(self, payload: dict[str, Any], model: str = "fake-llm") -> None:
        self.payload = payload
        self.model = model
        self.requests: list[LLMRequest] = []

    async def generate_structured(
        self, request: LLMRequest, response_model: type[StructuredModel]
    ) -> CandidateStructuredOutput[StructuredModel]:
        self.requests.append(request)
        return CandidateStructuredOutput(
            data=response_model.model_validate(self.payload), provider="fake", model=self.model
        )


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, dimensions: int, vector_factory: Callable[[str], list[float]] | None = None
    ) -> None:
        self.dimensions = dimensions
        self.vector_factory = vector_factory or (lambda _: [0.0] * dimensions)
        self.requests: list[list[str]] = []

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.requests.append(texts)
        vectors = [self.vector_factory(text) for text in texts]
        if any(len(vector) != self.dimensions for vector in vectors):
            from app.providers.contracts import StructuredOutputError

            raise StructuredOutputError(
                "Fake embedding vector dimensions did not match configuration."
            )
        return EmbeddingResult(vectors=vectors, model="fake-embedding", dimensions=self.dimensions)
