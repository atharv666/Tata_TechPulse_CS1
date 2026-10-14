"""Environment-backed, typed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RetrySettings(BaseModel):
    """Bounded request retry configuration shared by provider adapters."""

    max_attempts: int = Field(default=3, ge=1, le=8)
    initial_backoff_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    max_backoff_seconds: float = Field(default=60.0, ge=0.0, le=600.0)


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
    dimensions: int = Field(default=768, ge=1)
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
    embedding_dimensions: int = Field(default=768, ge=1)
    llm_provider: Literal["openai_compatible", "ollama", "fake"] | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    llm_max_attempts: int = Field(default=3, ge=1, le=8)
    llm_initial_backoff_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    embedding_provider: Literal["openai_compatible", "ollama", "gemini", "fake"] | None = None
    embedding_base_url: HttpUrl | None = None
    embedding_model: str | None = None
    embedding_model_version: str = "v1"
    embedding_api_key: SecretStr | None = None
    embedding_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    embedding_max_attempts: int = Field(default=4, ge=1, le=8)
    embedding_initial_backoff_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    chunk_target_tokens: int = Field(default=400, ge=32, le=4000)
    chunk_max_tokens: int = Field(default=800, ge=64, le=10000)
    chunk_overlap_tokens: int = Field(default=80, ge=0, le=1000)
    # OCR for scanned pages. "gemini" sends page images to a hosted API: development/synthetic data
    # only, and only with OCR_ALLOW_EXTERNAL=true. "tesseract" is local and private.
    ocr_provider: Literal["none", "tesseract", "gemini"] = "none"
    ocr_model: str | None = None
    ocr_base_url: HttpUrl | None = None
    ocr_api_key: SecretStr | None = None
    ocr_allow_external: bool = False
    ocr_tesseract_binary: str = "tesseract"
    ocr_language: str = "eng"
    ocr_min_chars: int = Field(default=30, ge=0, le=2000)
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    ocr_max_pages: int | None = Field(default=None, ge=1)
    document_source_dir: str = "data/sources"
    # Retrieval-augmented answering. Defaults are starting points; ``scripts/evaluate_rag.py``
    # measures recall/groundedness and is how they should be tuned for a given embedding model.
    rag_dense_k: int = Field(default=30, ge=1, le=200)
    rag_lexical_k: int = Field(default=30, ge=1, le=200)
    rag_rrf_k: int = Field(default=60, ge=1, le=200)
    rag_default_top_k: int = Field(default=8, ge=1, le=50)
    rag_max_chunks_per_section: int = Field(default=2, ge=1, le=10)
    rag_min_dense_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    rag_min_lexical_ratio: float = Field(default=0.34, ge=0.0, le=1.0)
    rag_context_token_budget: int = Field(default=3500, ge=200, le=60000)
    rag_parent_lead_tokens: int = Field(default=150, ge=0, le=2000)
    rag_neighbor_chunks: int = Field(default=1, ge=0, le=5)
    rag_max_rounds: int = Field(default=2, ge=1, le=4)
    rag_claim_support_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # Entity resolution: hash-map blocking proposes pairs, deterministic rules decide the obvious
    # ones, and the LLM only judges the ambiguous remainder (bounded per run, cached afterwards).
    resolution_llm_enabled: bool = True
    resolution_candidate_threshold: float = Field(default=0.62, ge=0.0, le=1.0)
    resolution_llm_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    resolution_llm_batch_size: int = Field(default=8, ge=1, le=25)
    resolution_max_llm_pairs: int = Field(default=200, ge=0, le=5000)
    resolution_max_block_size: int = Field(default=40, ge=2, le=1000)
    # When true, answers use only document versions whose header status is one of
    # ``approved_source_statuses`` (case-insensitive). Off by default so drafts can be explored.
    require_approved_sources: bool = False
    approved_source_statuses: list[str] = Field(
        default_factory=lambda: ["approved", "released", "baselined"]
    )
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    worker_lease_seconds: int = Field(default=900, ge=30, le=86400)
    embedding_batch_size: int = Field(default=32, ge=1, le=100)
    auth_mode: Literal["development", "enterprise"] = "development"
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost",
            "http://localhost:80",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    @field_validator("document_source_dir")
    @classmethod
    def anchor_source_dir(cls, value: str) -> str:
        """A relative upload directory is relative to the repository, not the working directory.

        The API and the worker are started from different folders; resolving against the current
        directory made them look in two different places, so the worker could not find uploads.
        """
        path = Path(value)
        return str(path if path.is_absolute() else (PROJECT_ROOT / path).resolve())

    def llm_settings(self) -> LLMProviderSettings:
        """Materialize the isolated LLM configuration consumed by the provider factory."""
        return LLMProviderSettings(
            provider=self.llm_provider,
            base_url=self.llm_base_url,
            model=self.llm_model,
            # Credentials are never borrowed across providers: the Groq key is only ever sent to the
            # LLM endpoint. Use LLM_API_KEY explicitly for any other OpenAI-compatible endpoint.
            api_key=self.llm_api_key or self.groq_api_key,
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
            # The Gemini key is only ever sent to the embedding endpoint (never the Groq key).
            api_key=self.embedding_api_key or self.gemini_api_key,
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
