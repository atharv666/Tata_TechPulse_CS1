"""Provider abstraction tests without contacting external model services."""

import asyncio
import json

import httpx
import pytest
from app.core.config import (
    EmbeddingProviderSettings,
    LLMProviderSettings,
    RetrySettings,
)
from app.providers.contracts import (
    LLMMessage,
    LLMRequest,
    ProviderConfigurationError,
    ProviderTimeoutError,
    StructuredOutputError,
)
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.providers.fake import FakeEmbeddingProvider, FakeLLMProvider
from app.providers.gemini import GeminiEmbeddingProvider
from app.providers.http import RetryingHttpClient
from app.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMProvider,
)
from pydantic import BaseModel, ValidationError


class ExtractionCandidate(BaseModel):
    name: str
    confidence: float


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def test_provider_factory_selects_only_explicit_provider() -> None:
    llm = create_llm_provider(LLMProviderSettings(provider="fake"))
    embeddings = create_embedding_provider(
        EmbeddingProviderSettings(provider="fake", dimensions=3)
    )

    assert isinstance(llm, FakeLLMProvider)
    assert isinstance(embeddings, FakeEmbeddingProvider)


def test_provider_factory_rejects_missing_selection() -> None:
    with pytest.raises(ProviderConfigurationError, match="selection is required"):
        create_llm_provider(LLMProviderSettings())


def test_selected_http_provider_requires_complete_configuration() -> None:
    with pytest.raises(ProviderConfigurationError, match="base_url and model"):
        create_llm_provider(LLMProviderSettings(provider="openai_compatible"))


def test_fake_llm_returns_typed_candidate_output() -> None:
    provider = FakeLLMProvider({"name": "BrakeController", "confidence": 0.91})
    request = LLMRequest(messages=[LLMMessage(role="user", content="extract")])

    result = run(provider.generate_structured(request, ExtractionCandidate))

    assert result.data.name == "BrakeController"  # type: ignore[union-attr]
    assert result.provider == "fake"  # type: ignore[union-attr]
    assert provider.requests == [request]


def test_fake_llm_rejects_invalid_structured_payload() -> None:
    provider = FakeLLMProvider({"name": "BrakeController"})
    request = LLMRequest(messages=[LLMMessage(role="user", content="extract")])

    with pytest.raises(ValidationError):
        run(provider.generate_structured(request, ExtractionCandidate))


def test_openai_compatible_response_validates_structured_output() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"name": "X"}'}}]}
        )
    )
    client = httpx.AsyncClient(base_url="https://model.example", transport=transport)
    provider = OpenAICompatibleLLMProvider(
        LLMProviderSettings(
            provider="openai_compatible",
            base_url="https://model.example",
            model="model",
        ),
        client=client,
    )

    with pytest.raises(StructuredOutputError):
        run(provider.generate_structured(LLMRequest(messages=[]), ExtractionCandidate))


def test_openai_compatible_preserves_configured_v1_prefix() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"name": "X", "confidence": 0.9}'}}
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://model.example/openai/v1/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleLLMProvider(
        LLMProviderSettings(
            provider="openai_compatible",
            base_url="https://model.example/openai/v1/",
            model="model",
        ),
        client=client,
    )

    run(provider.generate_structured(LLMRequest(messages=[]), ExtractionCandidate))

    assert requests[0].url.path == "/openai/v1/chat/completions"


def test_openai_compatible_embedding_preserves_configured_v1_prefix() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    client = httpx.AsyncClient(
        base_url="https://model.example/openai/v1/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleEmbeddingProvider(
        EmbeddingProviderSettings(
            provider="openai_compatible",
            base_url="https://model.example/openai/v1/",
            model="embedding-model",
            dimensions=2,
        ),
        client=client,
    )

    run(provider.embed(["document"]))

    assert requests[0].url.path == "/openai/v1/embeddings"


def test_gemini_provider_requests_configured_output_dimension() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "embeddings": [{"values": [0.1, 0.2, 0.3]}, {"values": [0.4, 0.5, 0.6]}]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        transport=httpx.MockTransport(handler),
    )
    provider = GeminiEmbeddingProvider(
        EmbeddingProviderSettings(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-embedding-2",
            api_key="test-key",
            dimensions=3,
        ),
        client=client,
    )

    result = run(provider.embed(["first", "second"]))

    assert result.dimensions == 3  # type: ignore[union-attr]
    assert (
        requests[0].url.path == "/v1beta/models/gemini-embedding-2:batchEmbedContents"
    )
    assert json.loads(requests[0].content)["requests"][0]["outputDimensionality"] == 3
    assert requests[0].headers["x-goog-api-key"] == "test-key"


def test_fake_embeddings_validate_dimension() -> None:
    provider = FakeEmbeddingProvider(dimensions=3, vector_factory=lambda _: [1.0, 2.0])

    with pytest.raises(StructuredOutputError, match="dimensions"):
        run(provider.embed(["signal"]))


def test_retrying_client_retries_transient_server_error() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, json={"ok": True})

    async def no_sleep(_: float) -> None:
        return None

    client = httpx.AsyncClient(
        base_url="https://model.example", transport=httpx.MockTransport(handler)
    )
    retrying = RetryingHttpClient(client, RetrySettings(max_attempts=2), sleep=no_sleep)

    response = run(retrying.post("/test", {}, {}))

    assert response.status_code == 200  # type: ignore[union-attr]
    assert calls == 2


def test_retrying_client_raises_timeout_after_bounded_attempts() -> None:
    async def no_sleep(_: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.AsyncClient(
        base_url="https://model.example", transport=httpx.MockTransport(handler)
    )
    retrying = RetryingHttpClient(client, RetrySettings(max_attempts=2), sleep=no_sleep)

    with pytest.raises(ProviderTimeoutError):
        run(retrying.post("/test", {}, {}))
