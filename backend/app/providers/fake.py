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
