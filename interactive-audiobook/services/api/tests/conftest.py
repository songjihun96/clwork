"""Test fixtures.

By default tests run against a temporary SQLite database and fakeredis, so they need no
services. Set TEST_DATABASE_URL (e.g. postgresql+asyncpg://...) to run the same suite
against PostgreSQL — required in CI before merging (see docs/roadmap.md, Phase 1).
"""

import hashlib
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from story_core.db.extensions import ensure_extensions
from story_core.jobs.queue import RecordingJobQueue
from story_core.models import Base
from story_core.models.user import IdentityProvider
from story_core.storage.local import LocalFileStorage
from story_core.storage.signing import MediaUrlSigner

from app.config import Settings
from app.main import create_app
from app.security.identity import (
    APPLE_ISSUERS,
    GOOGLE_ISSUERS,
    IdentityTokenVerifier,
    NonceMode,
    OidcIdTokenVerifier,
)

APPLE_CLIENT_ID = "com.example.audiobook"
GOOGLE_CLIENT_ID = "1234-test.apps.googleusercontent.com"
TEST_PASSWORD = "correct horse battery"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "redis_url": "redis://unused:6379/0",
        "jwt_secret": "test-secret-" + "x" * 40,
        "apple_client_ids": [APPLE_CLIENT_ID],
        "google_client_ids": [GOOGLE_CLIENT_ID],
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class StaticKeyResolver:
    def __init__(self, public_key: Any) -> None:
        self._key = public_key

    def get_signing_key(self, token: str) -> Any:
        return self._key


class IdTokenFactory:
    """Signs ID tokens the way Apple/Google would, with a locally generated RSA key."""

    def __init__(self) -> None:
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()

    def make(
        self,
        provider: IdentityProvider,
        *,
        subject: str = "provider-subject-1",
        email: str | None = "social@example.com",
        email_verified: Any = True,
        nonce: str | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        expires_in: int = 600,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": issuer or (APPLE_ISSUERS[0] if provider is IdentityProvider.APPLE else GOOGLE_ISSUERS[0]),
            "aud": audience or (APPLE_CLIENT_ID if provider is IdentityProvider.APPLE else GOOGLE_CLIENT_ID),
            "sub": subject,
            "iat": now,
            "exp": now + expires_in,
        }
        if email is not None:
            claims["email"] = email
            claims["email_verified"] = email_verified
        if nonce is not None:
            claims["nonce"] = (
                hashlib.sha256(nonce.encode()).hexdigest() if provider is IdentityProvider.APPLE else nonce
            )
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test"})


@pytest.fixture(scope="session")
def id_tokens() -> IdTokenFactory:
    return IdTokenFactory()


def make_verifiers(
    factory: IdTokenFactory, settings: Settings
) -> dict[IdentityProvider, IdentityTokenVerifier]:
    resolver = StaticKeyResolver(factory.public_key)
    return {
        IdentityProvider.APPLE: OidcIdTokenVerifier(
            provider=IdentityProvider.APPLE,
            issuers=APPLE_ISSUERS,
            audiences=settings.apple_client_ids,
            key_resolver=resolver,
            nonce_mode=NonceMode.SHA256,
        ),
        IdentityProvider.GOOGLE: OidcIdTokenVerifier(
            provider=IdentityProvider.GOOGLE,
            issuers=GOOGLE_ISSUERS,
            audiences=settings.google_client_ids,
            key_resolver=resolver,
            nonce_mode=NonceMode.PLAIN,
        ),
    }


AppFactory = Callable[..., FastAPI]


@pytest.fixture
async def app_factory(tmp_path: Path, id_tokens: IdTokenFactory) -> AsyncIterator[AppFactory]:
    created: list[FastAPI] = []

    def _factory(**settings_overrides: Any) -> FastAPI:
        settings = make_settings(tmp_path, **settings_overrides)
        app = create_app(
            settings,
            redis=FakeAsyncRedis(),
            identity_verifiers=make_verifiers(id_tokens, settings),
            storage=LocalFileStorage(
                tmp_path / "storage",
                signer=MediaUrlSigner(secret=b"m" * 32, base_url="http://testserver"),
            ),
            job_queue=RecordingJobQueue(),
            configure_logs=False,
        )
        created.append(app)
        return app

    yield _factory

    for app in created:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await app.state.redis.aclose()
        await app.state.engine.dispose()


async def _prepare(app: FastAPI) -> None:
    async with app.state.engine.begin() as conn:
        # create_all skips migrations, so the extensions they install must be ensured here.
        await ensure_extensions(conn)
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def app(app_factory: AppFactory) -> FastAPI:
    application = app_factory()
    await _prepare(application)
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def make_client(app: FastAPI) -> httpx.AsyncClient:
    await _prepare(app)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def register(
    client: httpx.AsyncClient, email: str | None = None, password: str = TEST_PASSWORD
) -> dict[str, Any]:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post("/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    body["_email"] = email
    return body


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
