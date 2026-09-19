"""Agent configuration.

Every name here is shared with the API and the worker on purpose: one `.env` drives the whole stack, and a
mismatch would be silent. Two mismatches in particular:

* a different ``TTS_PROVIDER``/``TTS_DEFAULT_VOICE`` means Talk mode synthesises narration the Listen path
  already paid for (the cache key includes both);
* a different ``EMBEDDING_MODEL`` means questions asked by voice search rows nobody indexed.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from story_core.db.session import DatabaseOptions
from story_core.models.rag import EMBEDDING_DIMENSIONS
from story_core.providers.registry import EmbeddingConfig, LLMConfig
from story_core.storage.factory import StorageConfig
from story_core.storage.s3 import S3Options


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    sentry_dsn: SecretStr | None = None

    database_url: str = "postgresql+asyncpg://audiobook:audiobook@localhost:5432/audiobook"
    # One job holds one pool; jobs are many and short-lived, so keep each small.
    database_pool_size: int = Field(default=2, ge=1, le=20)
    database_statement_timeout_ms: int = Field(default=10_000, ge=1000)

    # Same names the API uses; the agent needs the key pair to register as a worker.
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: SecretStr = SecretStr("secretsecretsecretsecretsecretsecretsecret")
    # Must match the API's REALTIME_AGENT_NAME, or dispatched jobs reach no worker.
    realtime_agent_name: str = "story-agent"
    # A deploy waits this long for live sessions to end before killing the process.
    drain_timeout_seconds: int = Field(default=600, ge=0, le=3600)

    # --- Narration and voice (must match the API and worker: they form the audio cache key) ---
    tts_provider: str = "fake"
    tts_default_voice: str = "fake-narrator"
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = Path("var/storage")
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    public_base_url: str = "http://localhost:8000"
    media_signing_secret: SecretStr = SecretStr("insecure-development-media-signing-secret-change-me")

    # --- Speech recognition ---
    stt_provider: str = "fake"
    # What the offline STT "hears", in order. Development and E2E only.
    # NoDecode: without it pydantic-settings tries to JSON-parse the env value before the validator runs.
    stt_fake_script: Annotated[tuple[str, ...], NoDecode] = ("하람은 누구야",)

    # --- Answering (must match the API) ---
    llm_provider: Literal["fake", "openai_compatible"] = "fake"
    llm_model: str = "fake-story-v1"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_supports_json_schema: bool = False
    embedding_provider: Literal["fake", "openai_compatible"] = "fake"
    embedding_model: str = "hashing-bigram-v1"
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    # The small classifier costs a model call per ambiguous utterance; off until a real endpoint exists.
    intent_classifier_enabled: bool = False

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
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("stt_fake_script", mode="before")
    @classmethod
    def _split_script(cls, value: object) -> object:
        # Pipe-separated so a script can contain commas: STT_FAKE_SCRIPT="하람은 누구야|멈춰"
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split("|") if item.strip())
        return value

    @property
    def agent_name(self) -> str:
        return self.realtime_agent_name

    @property
    def database_options(self) -> DatabaseOptions:
        return DatabaseOptions(
            url=self.database_url,
            application_name="audiobook-ai-agent",
            pool_size=self.database_pool_size,
            statement_timeout_ms=self.database_statement_timeout_ms,
        )

    def storage_config(self) -> StorageConfig:
        s3 = None
        if self.storage_backend == "s3":
            s3 = S3Options(
                bucket=self.s3_bucket or "",
                region=self.s3_region,
                endpoint_url=self.s3_endpoint_url,
                access_key_id=self.s3_access_key_id.get_secret_value() if self.s3_access_key_id else None,
                secret_access_key=self.s3_secret_access_key.get_secret_value()
                if self.s3_secret_access_key
                else None,
            )
        return StorageConfig(
            backend=self.storage_backend,
            local_root=self.storage_local_root,
            public_base_url=self.public_base_url,
            media_signing_secret=self.media_signing_secret.get_secret_value().encode(),
            s3=s3,
        )

    def llm_config(self) -> LLMConfig:
        return LLMConfig(
            provider=self.llm_provider,
            model=self.llm_model,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key.get_secret_value() if self.llm_api_key else None,
            supports_json_schema=self.llm_supports_json_schema,
        )

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
