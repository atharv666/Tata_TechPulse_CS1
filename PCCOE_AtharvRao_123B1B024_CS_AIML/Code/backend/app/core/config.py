"""Environment-backed, typed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RetrySettings(BaseModel):
    """Bounded request retry configuration shared by provider adapters."""

    max_attempts: int = Field(default=3, ge=1, le=5)
    initial_backoff_seconds: float = Field(default=0.1, ge=0.0, le=5.0)


class LLMProviderSettings(BaseModel):
    """Configuration for one LLM adapter; credentials never appear in responses or logs."""

    provider: Literal["openai_compatible", "ollama", "fake"] | None = None
    base_url: HttpUrl | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    retry: RetrySettings = Field(default_factory=RetrySettings)

    @field_validator("model")
    @classmethod
    def model_required_when_provider_selected(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("LLM model cannot be blank.")
        return value


class EmbeddingProviderSettings(BaseModel):
    """Configuration for one embedding adapter."""

    provider: Literal["openai_compatible", "ollama", "gemini", "fake"] | None = None
    base_url: HttpUrl | None = None
    model: str | None = None
    model_version: str = "v1"
    api_key: SecretStr | None = None
    dimensions: int = Field(default=1536, ge=1)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    retry: RetrySettings = Field(default_factory=RetrySettings)


class Settings(BaseSettings):
    """Settings shared by the API and future worker processes."""

    model_config = SettingsConfigDict(
        # The root file supplies shared defaults; backend/.env is the local
        # service configuration and therefore deliberately has precedence.
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AUTOSAR Architecture Intelligence Assistant"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Declared only for configuration compatibility. No database connection is made in Phase 1.
    database_url: str | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    embedding_dimensions: int = Field(default=1536, ge=1)
    llm_provider: Literal["openai_compatible", "ollama", "fake"] | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_initial_backoff_seconds: float = Field(default=0.1, ge=0.0, le=5.0)
    embedding_provider: Literal["openai_compatible", "ollama", "gemini", "fake"] | None = None
    embedding_base_url: HttpUrl | None = None
    embedding_model: str | None = None
    embedding_model_version: str = "v1"
    embedding_api_key: SecretStr | None = None
    embedding_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    embedding_max_attempts: int = Field(default=3, ge=1, le=5)
    embedding_initial_backoff_seconds: float = Field(default=0.1, ge=0.0, le=5.0)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    chunk_max_tokens: int = Field(default=800, ge=64, le=10000)
    chunk_overlap_tokens: int = Field(default=80, ge=0, le=1000)
    document_source_dir: str = "data/sources"
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    auth_mode: Literal["development", "enterprise"] = "development"
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost",
            "http://localhost:80",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    def llm_settings(self) -> LLMProviderSettings:
        """Materialize the isolated LLM configuration consumed by the provider factory."""
        return LLMProviderSettings(
            provider=self.llm_provider,
            base_url=self.llm_base_url,
            model=self.llm_model,
            api_key=self.llm_api_key or self.groq_api_key or self.gemini_api_key,
            timeout_seconds=self.llm_timeout_seconds,
            retry=RetrySettings(
                max_attempts=self.llm_max_attempts,
                initial_backoff_seconds=self.llm_initial_backoff_seconds,
            ),
        )

    def embedding_settings(self) -> EmbeddingProviderSettings:
        """Materialize the isolated embedding configuration consumed by the factory."""
        return EmbeddingProviderSettings(
            provider=self.embedding_provider,
            base_url=self.embedding_base_url or self.llm_base_url,
            model=self.embedding_model,
            model_version=self.embedding_model_version,
            api_key=self.embedding_api_key or self.gemini_api_key or self.groq_api_key,
            dimensions=self.embedding_dimensions,
            timeout_seconds=self.embedding_timeout_seconds,
            retry=RetrySettings(
                max_attempts=self.embedding_max_attempts,
                initial_backoff_seconds=self.embedding_initial_backoff_seconds,
            ),
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance for the current process."""
    return Settings()
