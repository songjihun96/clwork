"""Worker process entrypoint.

    taskiq worker worker.main:broker --workers 2

Each worker process opens its own database pool and storage client at startup.
"""

from pathlib import Path
from typing import Literal

import sentry_sdk
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from story_core.audio.encoding import build_encoder
from story_core.audio.renderer import ParagraphAudioRenderer
from story_core.db.session import DatabaseOptions, create_engine, create_sessionmaker
from story_core.jobs.queue import create_broker
from story_core.logging import configure_logging
from story_core.models.rag import EMBEDDING_DIMENSIONS
from story_core.providers.registry import EmbeddingConfig, build_resilient_embedding
from story_core.providers.tts.registry import build_tts_provider
from story_core.rag.index import ChunkIndexer
from story_core.storage.factory import StorageConfig, build_storage
from story_core.storage.s3 import S3Options
from taskiq import TaskiqEvents, TaskiqState

from worker.tasks import WorkerResources, register_tasks


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://audiobook:audiobook@localhost:5432/audiobook"
    database_pool_size: int = Field(default=5, ge=1, le=50)
    # Ingestion writes many rows in one transaction; allow longer statements than the API.
    database_statement_timeout_ms: int = Field(default=120_000, ge=1000)
    redis_url: str = "redis://localhost:6379/0"
    sentry_dsn: SecretStr | None = None

    # Storage and narration settings must match the API (same env vars), or cache keys and objects differ.
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = Path("var/storage")
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    public_base_url: str = "http://localhost:8000"
    media_signing_secret: SecretStr = SecretStr("insecure-development-media-signing-secret-change-me")
    tts_provider: str = "fake"
    audio_format: Literal["wav", "aac"] = "wav"

    # Embedding settings must match the API: a different model id would index into rows the API never
    # queries, leaving questions silently unanswerable.
    embedding_provider: Literal["fake", "openai_compatible"] = "fake"
    embedding_model: str = "hashing-bigram-v1"
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""

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

    @field_validator(
        "sentry_dsn",
        "s3_bucket",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "embedding_base_url",
        "embedding_api_key",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        return None if value == "" else value

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


settings = WorkerSettings()
broker = create_broker(settings.redis_url)
_resources: WorkerResources | None = None


def _get_resources() -> WorkerResources:
    if _resources is None:
        raise RuntimeError("worker resources are not initialised (startup event did not run)")
    return _resources


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(state: TaskiqState) -> None:
    global _resources
    configure_logging(settings.log_level)
    if settings.sentry_dsn is not None:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.env,
            send_default_pii=False,
            include_local_variables=False,
        )
    engine = create_engine(
        DatabaseOptions(
            url=settings.database_url,
            application_name="audiobook-worker",
            pool_size=settings.database_pool_size,
            statement_timeout_ms=settings.database_statement_timeout_ms,
        )
    )
    state.engine = engine
    sessionmaker = create_sessionmaker(engine)
    storage = build_storage(settings.storage_config())
    renderer = ParagraphAudioRenderer(
        sessionmaker, storage, build_tts_provider(settings.tts_provider), build_encoder(settings.audio_format)
    )
    embedder = build_resilient_embedding(settings.embedding_config())
    if embedder.dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"embedding width {embedder.dimensions} != column width {EMBEDDING_DIMENSIONS}; "
            "a different model needs its own table and a backfill"
        )
    _resources = WorkerResources(sessionmaker, storage, renderer, ChunkIndexer(sessionmaker, embedder))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    engine = getattr(state, "engine", None)
    if engine is not None:
        await engine.dispose()


register_tasks(broker, _get_resources)
