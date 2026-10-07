"""Explicit configuration-driven provider selection with no silent fallback."""

from app.core.config import EmbeddingProviderSettings, LLMProviderSettings
from app.providers.contracts import EmbeddingProvider, LLMProvider, ProviderConfigurationError
from app.providers.fake import FakeEmbeddingProvider, FakeLLMProvider
from app.providers.gemini import GeminiEmbeddingProvider
from app.providers.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from app.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMProvider,
)


def create_llm_provider(settings: LLMProviderSettings) -> LLMProvider:
    """Create only the provider explicitly selected in application configuration."""
    if settings.provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(settings)
    if settings.provider == "ollama":
        return OllamaLLMProvider(settings)
    if settings.provider == "fake":
        return FakeLLMProvider(payload={})
    raise ProviderConfigurationError(
        "LLM provider selection is required; no fallback is configured."
    )


def create_embedding_provider(settings: EmbeddingProviderSettings) -> EmbeddingProvider:
    """Create only the provider explicitly selected in application configuration."""
    if settings.provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(settings)
    if settings.provider == "ollama":
        return OllamaEmbeddingProvider(settings)
    if settings.provider == "gemini":
        return GeminiEmbeddingProvider(settings)
    if settings.provider == "fake":
        return FakeEmbeddingProvider(dimensions=settings.dimensions)
    raise ProviderConfigurationError(
        "Embedding provider selection is required; no fallback is configured."
    )
