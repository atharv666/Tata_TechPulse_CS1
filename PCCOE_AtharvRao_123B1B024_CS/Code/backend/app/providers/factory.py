"""Explicit configuration-driven provider selection with no silent fallback."""

from app.core.config import EmbeddingProviderSettings, LLMProviderSettings
from app.providers.contracts import EmbeddingProvider, LLMProvider, ProviderConfigurationError
from app.providers.fake import create_fake_embedding, create_fake_llm
from app.providers.gemini import GeminiEmbeddingProvider
from app.providers.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from app.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMProvider,
)


def create_llm_provider(settings: LLMProviderSettings) -> LLMProvider:
    """Create only the provider explicitly selected in application configuration."""
    provider: LLMProvider
    if settings.provider == "openai_compatible":
        provider = OpenAICompatibleLLMProvider(settings)
    elif settings.provider == "ollama":
        provider = OllamaLLMProvider(settings)
    elif settings.provider == "fake":
        provider = create_fake_llm()
    else:
        raise ProviderConfigurationError(
            "LLM provider selection is required; no fallback is configured."
        )
    return provider


def create_embedding_provider(settings: EmbeddingProviderSettings) -> EmbeddingProvider:
    """Create only the provider explicitly selected in application configuration."""
    provider: EmbeddingProvider
    if settings.provider == "openai_compatible":
        provider = OpenAICompatibleEmbeddingProvider(settings)
    elif settings.provider == "ollama":
        provider = OllamaEmbeddingProvider(settings)
    elif settings.provider == "gemini":
        provider = GeminiEmbeddingProvider(settings)
    elif settings.provider == "fake":
        provider = create_fake_embedding(settings.dimensions)
    else:
        raise ProviderConfigurationError(
            "Embedding provider selection is required; no fallback is configured."
        )
    return provider
