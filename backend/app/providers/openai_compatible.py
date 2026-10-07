"""OpenAI-compatible HTTP adapter; usable with approved compatible endpoints."""

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


class OpenAICompatibleLLMProvider(LLMProvider):
    """Adapter for the OpenAI Chat Completions-compatible structured-output contract."""

    def __init__(
        self, settings: LLMProviderSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if settings.base_url is None or settings.model is None:
            raise ProviderConfigurationError("OpenAI-compatible LLM requires base_url and model.")
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
            # This is deliberately a relative path.  Compatible providers commonly
            # configure a base URL ending in `/v1` (for example Groq), so adding a
            # second `/v1` here would make a broken `/v1/v1/...` request.
            "chat/completions",
            {
                "model": self._model,
                "messages": [message.model_dump() for message in request.messages],
                "temperature": request.temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "schema": response_model.model_json_schema(),
                    },
                },
            },
            self._headers(),
        )
        try:
            content = response.json()["choices"][0]["message"]["content"]
            payload: dict[str, Any] = content if isinstance(content, dict) else json.loads(content)
            data = response_model.model_validate(payload)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise StructuredOutputError(
                "OpenAI-compatible response did not match the requested schema."
            ) from error
        return CandidateStructuredOutput(data=data, provider="openai_compatible", model=self._model)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.api_key.get_secret_value()}"
        return headers


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Adapter for the OpenAI-compatible Embeddings endpoint."""

    def __init__(
        self, settings: EmbeddingProviderSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if settings.base_url is None or settings.model is None:
            raise ProviderConfigurationError(
                "OpenAI-compatible embeddings require base_url and model."
            )
        self._settings = settings
        self._model: str = settings.model
        self._client = client or httpx.AsyncClient(
            base_url=str(settings.base_url), timeout=settings.timeout_seconds
        )
        self._http = RetryingHttpClient(self._client, settings.retry)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        response = await self._http.post(
            # Keep the configured compatible API prefix intact; see the LLM adapter
            # above for why this must not start with `/v1`.
            "embeddings",
            {"model": self._model, "input": texts},
            self._headers(),
        )
        try:
            vectors = [item["embedding"] for item in response.json()["data"]]
        except (KeyError, TypeError) as error:
            raise StructuredOutputError("Embedding response did not contain vectors.") from error
        result = EmbeddingResult(
            vectors=vectors, model=self._model, dimensions=self._settings.dimensions
        )
        _validate_embeddings(result, len(texts), self._settings.dimensions)
        return result

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key is not None:
            headers["Authorization"] = f"Bearer {self._settings.api_key.get_secret_value()}"
        return headers


def _validate_embeddings(result: EmbeddingResult, text_count: int, dimensions: int) -> None:
    if len(result.vectors) != text_count or any(
        len(vector) != dimensions for vector in result.vectors
    ):
        raise StructuredOutputError("Embedding count or dimensions did not match configuration.")
