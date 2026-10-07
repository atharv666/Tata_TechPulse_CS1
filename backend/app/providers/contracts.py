"""Provider-neutral LLM and embedding contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel


class ProviderError(RuntimeError):
    """Base exception for a provider call that cannot produce a valid result."""


class ProviderConfigurationError(ProviderError):
    """Raised for an incomplete or unsupported explicitly selected provider."""


class ProviderTimeoutError(ProviderError):
    """Raised when the bounded provider request timeout is exhausted."""


class StructuredOutputError(ProviderError):
    """Raised when a provider response does not satisfy the requested Pydantic schema."""


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    temperature: float = 0.0


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str
    dimensions: int


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class CandidateStructuredOutput(BaseModel, Generic[StructuredModel]):
    """Typed provider output that remains candidate information until later validation."""

    data: StructuredModel
    provider: str
    model: str


class LLMProvider(ABC):
    """Provider-neutral structured generation interface."""

    @abstractmethod
    async def generate_structured(
        self, request: LLMRequest, response_model: type[StructuredModel]
    ) -> CandidateStructuredOutput[StructuredModel]:
        """Generate and validate candidate output against the caller-provided schema."""


class EmbeddingProvider(ABC):
    """Provider-neutral batch embedding interface."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Return one validated vector per supplied text."""
