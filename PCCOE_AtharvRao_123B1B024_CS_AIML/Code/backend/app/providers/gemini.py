"""Native Gemini embeddings adapter with explicit output dimensionality."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.core.config import EmbeddingProviderSettings
from app.providers.contracts import (
    EmbeddingProvider,
    EmbeddingResult,
    ProviderConfigurationError,
    StructuredOutputError,
)
from app.providers.http import RetryingHttpClient
from app.providers.openai_compatible import _validate_embeddings


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Call Gemini's native embedding API so configured dimensions are enforced.

    Gemini's OpenAI-compatible endpoint is useful for portability, but does not
    document output-size control. The native endpoint explicitly supports it.
    """

    def __init__(
        self, settings: EmbeddingProviderSettings, client: httpx.AsyncClient | None = None
    ) -> None:
        if settings.model is None or settings.api_key is None:
            raise ProviderConfigurationError("Gemini embeddings require model and API key.")
        self._settings = settings
        self._api_key = settings.api_key.get_secret_value()
        self._model = settings.model.removeprefix("models/")
        base_url = self._native_base_url(settings)
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=settings.timeout_seconds
        )
        self._http = RetryingHttpClient(self._client, settings.retry)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[], model=self._model, dimensions=self._settings.dimensions
            )
        request_model = f"models/{self._model}"
        payload: dict[str, object] = {
            "requests": [
                {
                    "model": request_model,
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self._settings.dimensions,
                }
                for text in texts
            ]
        }
        endpoint = f"models/{quote(self._model, safe='')}:batchEmbedContents"
        response = await self._http.post(endpoint, payload, self._headers())
        try:
            vectors = [item["values"] for item in response.json()["embeddings"]]
        except (KeyError, TypeError) as error:
            raise StructuredOutputError(
                "Gemini embedding response did not contain vectors."
            ) from error
        result = EmbeddingResult(
            vectors=vectors, model=self._model, dimensions=self._settings.dimensions
        )
        _validate_embeddings(result, len(texts), self._settings.dimensions)
        return result

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

    @staticmethod
    def _native_base_url(settings: EmbeddingProviderSettings) -> str:
        """Accept either a native Gemini base URL or the compatibility base URL."""
        if settings.base_url is None:
            return "https://generativelanguage.googleapis.com/v1beta/"
        value = str(settings.base_url).rstrip("/")
        if value.endswith("/openai"):
            value = value.removesuffix("/openai")
        return f"{value}/"
