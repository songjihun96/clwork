"""Environment-based configuration.

Every tunable value comes from environment variables (or `.env` in development).
Production refuses to start with insecure defaults.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from story_core.db.session import DatabaseOptions
from story_core.models.rag import EMBEDDING_DIMENSIONS
from story_core.providers.registry import EmbeddingConfig, LLMConfig
from story_core.storage.factory import StorageConfig
from story_core.storage.s3 import S3Options

from app.security.realtime import RealtimeConfig

MIN_JWT_SECRET_BYTES = 32
# Deliberately recognisable so it can be rejected in production.
INSECURE_DEV_JWT_SECRET = "insecure-development-secret-do-not-use-in-production"  # noqa: S105
INSECURE_DEV_MEDIA_SECRET = "insecure-development-media-signing-secret-change-me"  # noqa: S105
# The key baked into `livekit-server --dev`; usable locally, refused in production.
INSECURE_DEV_LIVEKIT_KEY = "devkey"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.DEVELOPMENT
    app_name: str = "audiobook-api"
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://audiobook:audiobook@localhost:5432/audiobook"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_connect_timeout_s: float = Field(default=5.0, gt=0)
    database_statement_timeout_ms: int = Field(default=5000, ge=100)

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    redis_timeout_s: float = Field(default=2.0, gt=0)

    # --- Auth tokens ---
    jwt_secret: SecretStr = SecretStr(INSECURE_DEV_JWT_SECRET)
    jwt_issuer: str = "audiobook-api"
    jwt_audience: str = "audiobook-mobile"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, ge=3600)
    # Social-only accounts (no password) must have authenticated this recently to delete the account.
    recent_auth_window_seconds: int = Field(default=600, ge=60)

    # --- Social sign-in (client IDs are public identifiers, not secrets) ---
    apple_client_ids: Annotated[list[str], NoDecode] = []
    google_client_ids: Annotated[list[str], NoDecode] = []
    identity_jwks_timeout_s: float = Field(default=5.0, gt=0)

    # --- HTTP ---
    cors_origins: Annotated[list[str], NoDecode] = []
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)
    enable_api_docs: bool | None = None

    # --- Rate limiting (fixed window) ---
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=300, ge=1)
    rate_limit_login_per_ip: int = Field(default=30, ge=1)
    rate_limit_login_per_account: int = Field(default=10, ge=1)
    rate_limit_register_per_ip: int = Field(default=10, ge=1)
    rate_limit_refresh_per_ip: int = Field(default=120, ge=1)

    # --- Storage ---
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = Path("var/storage")
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # Cloudflare R2: https://<account_id>.r2.cloudflarestorage.com
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Public origin of this API; local-storage media URLs are built from it.
    public_base_url: str = "http://localhost:8000"
    media_signing_secret: SecretStr = SecretStr(INSECURE_DEV_MEDIA_SECRET)
    media_url_ttl_seconds: int = Field(default=3600, ge=60, le=24 * 3600)

    # --- Narration (TTS) — must match the worker, or cache keys differ ---
    tts_provider: str = "fake"
    tts_default_voice: str = "fake-narrator"
    audio_format: Literal["wav", "aac"] = "wav"

    # --- Questions (RAG) — provider settings must match the worker ---
    llm_provider: Literal["fake", "openai_compatible"] = "fake"
    llm_model: str = "fake-story-v1"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_supports_json_schema: bool = False
    llm_timeout_s: float = Field(default=30.0, gt=0, le=120)
    embedding_provider: Literal["fake", "openai_compatible"] = "fake"
    embedding_model: str = "hashing-bigram-v1"
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    # Questions cost money per call, so they are rate limited more tightly than reads.
    question_rate_limit_per_minute: int = Field(default=12, ge=1, le=600)

    # --- Realtime (LiveKit, Talk mode) ---
    # Empty keys disable the endpoint (503) instead of failing at request time.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: SecretStr | None = None
    realtime_agent_name: str = "story-agent"
    realtime_token_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    # Reader + agent only. A leaked token must not be able to add a silent listener.
    realtime_max_participants: int = Field(default=2, ge=2, le=8)
    realtime_empty_timeout_seconds: int = Field(default=60, ge=5, le=600)
    realtime_rate_limit_per_minute: int = Field(default=10, ge=1, le=600)

    # --- Book uploads (admin) ---
    book_upload_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)

    # --- Observability ---
    sentry_dsn: SecretStr | None = None

    @field_validator("apple_client_ids", "google_client_ids", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "sentry_dsn",
        "s3_bucket",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "llm_base_url",
        "llm_api_key",
        "embedding_base_url",
        "embedding_api_key",
        "livekit_api_secret",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: Any) -> Any:
        return None if value == "" else value

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if len(secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        media_secret = self.media_signing_secret.get_secret_value()
        if len(media_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"MEDIA_SIGNING_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        if self.env is Environment.PRODUCTION:
            if secret == INSECURE_DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set explicitly in production")
            if media_secret == INSECURE_DEV_MEDIA_SECRET:
                raise ValueError("MEDIA_SIGNING_SECRET must be set explicitly in production")
            if media_secret == secret:
                raise ValueError("MEDIA_SIGNING_SECRET must differ from JWT_SECRET")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
            if self.tts_provider == "fake":
                raise ValueError("TTS_PROVIDER=fake is for development only")
            if self.llm_provider == "fake":
                raise ValueError("LLM_PROVIDER=fake is for development only")
            if self.embedding_provider == "fake":
                raise ValueError("EMBEDDING_PROVIDER=fake is for development only")
            if self.realtime_configured:
                if self.livekit_api_key == INSECURE_DEV_LIVEKIT_KEY:
                    raise ValueError("LIVEKIT_API_KEY must not be the development key in production")
                if not self.livekit_url.startswith("wss://"):
                    raise ValueError("LIVEKIT_URL must use wss in production")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL must use https in production")
        return self

    @property
    def realtime_configured(self) -> bool:
        """Talk mode is available only when all three values are present."""
        return bool(self.livekit_url and self.livekit_api_key and self.livekit_api_secret)

    @property
    def realtime_config(self) -> RealtimeConfig:
        if self.livekit_api_secret is None or not self.realtime_configured:
            raise ValueError("LiveKit is not configured")
        return RealtimeConfig(
            url=self.livekit_url,
            api_key=self.livekit_api_key,
            api_secret=self.livekit_api_secret.get_secret_value(),
            agent_name=self.realtime_agent_name,
            ttl_seconds=self.realtime_token_ttl_seconds,
            max_participants=self.realtime_max_participants,
            empty_timeout_seconds=self.realtime_empty_timeout_seconds,
        )

    @property
    def llm_config(self) -> LLMConfig:
        return LLMConfig(
            provider=self.llm_provider,
            model=self.llm_model,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key.get_secret_value() if self.llm_api_key else None,
            supports_json_schema=self.llm_supports_json_schema,
        )

    @property
    def embedding_config(self) -> EmbeddingConfig:
        return EmbeddingConfig(
            provider=self.embedding_provider,
            dimensions=EMBEDDING_DIMENSIONS,
            model=self.embedding_model,
            base_url=self.embedding_base_url,
            api_key=self.embedding_api_key.get_secret_value() if self.embedding_api_key else None,
            query_prefix=self.embedding_query_prefix,
            document_prefix=self.embedding_document_prefix,
        )

    @property
    def storage_config(self) -> StorageConfig:
        s3 = None
        if self.storage_backend == "s3":
            s3 = S3Options(
                bucket=self.s3_bucket or "",
                region=self.s3_region,
                endpoint_url=self.s3_endpoint_url,
                access_key_id=self.s3_access_key_id.get_secret_value() if self.s3_access_key_id else None,
                secret_access_key=(
                    self.s3_secret_access_key.get_secret_value() if self.s3_secret_access_key else None
                ),
            )
        return StorageConfig(
            backend=self.storage_backend,
            local_root=self.storage_local_root,
            public_base_url=self.public_base_url,
            media_signing_secret=self.media_signing_secret.get_secret_value().encode(),
            s3=s3,
        )

    @property
    def database_options(self) -> DatabaseOptions:
        return DatabaseOptions(
            url=self.database_url,
            application_name=self.app_name,
            pool_size=self.database_pool_size,
            connect_timeout_s=self.database_connect_timeout_s,
            statement_timeout_ms=self.database_statement_timeout_ms,
        )

    @property
    def api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.env is not Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
