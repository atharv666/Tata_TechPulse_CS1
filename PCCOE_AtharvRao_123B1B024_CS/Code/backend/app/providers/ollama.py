"""Local Ollama adapters isolated behind provider-neutral contracts."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import EmbeddingProviderSettings, LLMProviderSettings
from app.providers.contracts import (
    CandidateStructuredOutput,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMRequest,
    ProviderConfigurationError,
    StructuredModel,
    StructuredOutputError,
)
from app.providers.http import RetryingHttpClient
from app.providers.openai_compatible import _validate_embeddings


class OllamaLLMProvider(LLMProvider):
    """Adapter for Ollama's local `/api/chat` structured JSON response format."""

    def __init__(
        self, settings: LLMProviderSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if settings.base_url is None or settings.model is None:
            raise ProviderConfigurationError("Ollama LLM requires base_url and model.")
        self._settings = settings
        self._model: str = settings.model
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.base_url), timeout=settings.timeout_seconds
        )
        self._http = RetryingHttpClient(self._client, settings.retry)

    async def generate_structured(
        self, request: LLMRequest, response_model: type[StructuredModel]
    ) -> CandidateStructuredOutput[StructuredModel]:
        response = await self._http.post(
            "/api/chat",
            {
                "model": self._model,
                "messages": [message.model_dump() for message in request.messages],
                "format": response_model.model_json_schema(),
                "stream": False,
                "options": {"temperature": request.temperature},
            },
            {"Content-Type": "application/json"},
        )
        try:
            content = response.json()["message"]["content"]
            payload: dict[str, Any] = content if isinstance(content, dict) else json.loads(content)
            data = response_model.model_validate(payload)
        except (KeyError, TypeError, ValueError) as error:
            raise StructuredOutputError(
                "Ollama response did not match the requested schema."
            ) from error
        return CandidateStructuredOutput(data=data, provider="ollama", model=self._model)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Adapter for Ollama's local embedding endpoint."""

    def __init__(
        self, settings: EmbeddingProviderSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if settings.base_url is None or settings.model is None:
            raise ProviderConfigurationError("Ollama embeddings require base_url and model.")
        self._settings = settings
        self._model: str = settings.model
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.base_url), timeout=settings.timeout_seconds
        )
        self._http = RetryingHttpClient(self._client, settings.retry)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        response = await self._http.post(
            "/api/embed",
            {"model": self._model, "input": texts},
            {"Content-Type": "application/json"},
        )
        try:
            vectors = response.json()["embeddings"]
        except (KeyError, TypeError) as error:
            raise StructuredOutputError(
                "Ollama embedding response did not contain vectors."
            ) from error
        result = EmbeddingResult(
            vectors=vectors, model=self._model, dimensions=self._settings.dimensions
        )
        _validate_embeddings(result, len(texts), self._settings.dimensions)
        return result
