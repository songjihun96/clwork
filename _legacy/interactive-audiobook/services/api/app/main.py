"""Application factory.

Run with:  uvicorn app.main:create_app --factory
"""

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from story_core.audio.renderer import ParagraphAudioRenderer
from story_core.db.session import create_engine, create_sessionmaker
from story_core.jobs.queue import JobQueue, TaskiqJobQueue, create_broker
from story_core.logging import configure_logging
from story_core.models.rag import EMBEDDING_DIMENSIONS
from story_core.models.user import IdentityProvider
from story_core.providers.registry import build_resilient_embedding, build_resilient_llm
from story_core.providers.tts.registry import build_tts_provider
from story_core.rag.context import STORY_ANSWER_PROMPT, load_prompt
from story_core.storage.base import StorageProvider
from story_core.storage.factory import build_storage

from app.api import health, v1_router
from app.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.security.identity import IdentityTokenVerifier, build_identity_verifiers
from app.security.ratelimit import RateLimiter, RedisRateLimiter
from app.security.realtime import RealtimeTokenIssuer
from app.security.tokens import TokenService
from app.security.uploads import NoopUploadScanner, UploadScanner

API_VERSION = "0.2.0"
logger = logging.getLogger(__name__)


def _init_sentry(settings: Settings) -> None:
    if settings.sentry_dsn is None:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.env.value,
        release=API_VERSION,
        send_default_pii=False,
        include_local_variables=False,  # stack locals may hold passwords or tokens
        max_request_body_size="never",
        traces_sample_rate=0.0,
    )


def create_app(
    settings: Settings | None = None,
    *,
    redis: Redis | None = None,
    rate_limiter: RateLimiter | None = None,
    identity_verifiers: Mapping[IdentityProvider, IdentityTokenVerifier] | None = None,
    storage: StorageProvider | None = None,
    job_queue: JobQueue | None = None,
    upload_scanner: UploadScanner | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    if configure_logs:
        configure_logging(settings.log_level)
    _init_sentry(settings)

    engine = create_engine(settings.database_options)
    redis_client = redis or Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_timeout_s,
        socket_connect_timeout=settings.redis_timeout_s,
    )
    broker = None
    if job_queue is None:
        broker = create_broker(settings.redis_url)
        job_queue = TaskiqJobQueue(broker)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        broker_started = False
        if broker is not None:
            # Redis being down must not keep the API from serving reads; enqueueing then fails with 503.
            try:
                await broker.startup()
                broker_started = True
            except Exception as exc:
                logger.warning("job_broker_startup_failed", extra={"exc_type": type(exc).__name__})
        yield
        if broker is not None and broker_started:
            await broker.shutdown()
        await redis_client.aclose()
        await engine.dispose()

    app = FastAPI(
        title="Interactive Audiobook API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis_client
    app.state.rate_limiter = rate_limiter or RedisRateLimiter(redis_client)
    app.state.token_service = TokenService(
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_ttl=timedelta(seconds=settings.access_token_ttl_seconds),
    )
    app.state.identity_verifiers = dict(identity_verifiers or build_identity_verifiers(settings))
    app.state.storage = storage or build_storage(settings.storage_config)
    # Lookup-only: the API computes cache keys and hands out URLs; rendering happens in the worker.
    app.state.audio_renderer = ParagraphAudioRenderer(
        app.state.sessionmaker,
        app.state.storage,
        build_tts_provider(settings.tts_provider),
        None,
        audio_format=settings.audio_format,
    )
    # AI providers are built once per process: every key stays on the server, and the mobile app only
    # ever sees answers (docs/architecture.md §42).
    app.state.llm = build_resilient_llm(settings.llm_config)
    embedder = build_resilient_embedding(settings.embedding_config)
    if embedder.dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"embedding width {embedder.dimensions} != column width {EMBEDDING_DIMENSIONS}; "
            "a different model needs its own table and a backfill"
        )
    app.state.embedder = embedder
    # Fail at boot, not on a user's first question: a missing template means a packaging mistake.
    load_prompt(STORY_ANSWER_PROMPT)
    # Talk mode is optional: without LiveKit keys the endpoint answers 503 and Listen mode is unaffected.
    app.state.realtime_issuer = (
        RealtimeTokenIssuer(settings.realtime_config) if settings.realtime_configured else None
    )
    app.state.job_queue = job_queue
    app.state.upload_scanner = upload_scanner or NoopUploadScanner()

    install_exception_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["authorization", "content-type", "x-request-id", "x-device-id"],
        )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(v1_router)
    return app
