"""Pure unit tests (no app, no database)."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr, ValidationError
from starlette.requests import Request
from story_core.logging import REDACTED, JsonFormatter

from app.config import INSECURE_DEV_JWT_SECRET, INSECURE_DEV_MEDIA_SECRET, Settings
from app.core.errors import Unauthorized
from app.security import passwords
from app.security.ratelimit import InMemoryRateLimiter, RedisRateLimiter, client_ip
from app.security.tokens import TokenService, generate_refresh_token, hash_refresh_token

# ---------- config ----------


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET must be set explicitly"):
        Settings(_env_file=None, env="production", jwt_secret=INSECURE_DEV_JWT_SECRET)


def test_short_jwt_secret_rejected_everywhere() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None, env="development", jwt_secret="short")


# A minimally safe production configuration: every offline development provider replaced.
PRODUCTION_BASE: dict[str, object] = {
    "env": "production",
    "jwt_secret": "p" * 40,
    "media_signing_secret": "m" * 40,
    "public_base_url": "https://api.example.com",
    "tts_provider": "azure",
    "llm_provider": "openai_compatible",
    "embedding_provider": "openai_compatible",
}


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"media_signing_secret": INSECURE_DEV_MEDIA_SECRET}, "MEDIA_SIGNING_SECRET must be set"),
        ({"media_signing_secret": "p" * 40}, "must differ from JWT_SECRET"),
        ({"tts_provider": "fake"}, "TTS_PROVIDER=fake"),
        # Talk mode in production must not use the well-known development key pair or plain ws.
        (
            {"livekit_url": "ws://lk.example.com", "livekit_api_key": "k", "livekit_api_secret": "s" * 40},
            "LIVEKIT_URL must use wss",
        ),
        (
            {
                "livekit_url": "wss://lk.example.com",
                "livekit_api_key": "devkey",
                "livekit_api_secret": "s" * 40,
            },
            "LIVEKIT_API_KEY",
        ),
        ({"llm_provider": "fake"}, "LLM_PROVIDER=fake"),
        ({"embedding_provider": "fake"}, "EMBEDDING_PROVIDER=fake"),
        ({"public_base_url": "http://api.example.com"}, "PUBLIC_BASE_URL"),
        ({"storage_backend": "s3"}, "S3_BUCKET"),
    ],
)
def test_production_safety_checks(override: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{**PRODUCTION_BASE, **override})  # type: ignore[arg-type]


def test_production_settings_accepted_when_safe() -> None:
    settings = Settings(_env_file=None, **PRODUCTION_BASE)  # type: ignore[arg-type]
    assert settings.api_docs_enabled is False


def test_talk_mode_is_off_until_all_three_livekit_values_are_present() -> None:
    """A half-configured LiveKit must not look enabled: the endpoint would fail per request instead."""
    assert Settings(_env_file=None).realtime_configured is False
    partial = Settings(_env_file=None, livekit_url="ws://localhost:7880", livekit_api_key="devkey")
    assert partial.realtime_configured is False
    with pytest.raises(ValueError, match="not configured"):
        _ = partial.realtime_config

    full = Settings(
        _env_file=None,
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="s" * 40,
    )
    assert full.realtime_configured is True
    config = full.realtime_config
    assert config.agent_name == "story-agent" and config.max_participants == 2
    assert config.ttl_seconds == 600 and config.api_secret == "s" * 40


def test_app_builds_a_token_issuer_only_when_livekit_is_configured(tmp_path: Path) -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    without = create_app(make_settings(tmp_path), redis=FakeAsyncRedis(), configure_logs=False)
    assert without.state.realtime_issuer is None

    settings = make_settings(
        tmp_path,
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="s" * 40,
    )
    with_talk = create_app(settings, redis=FakeAsyncRedis(), configure_logs=False)
    assert with_talk.state.realtime_issuer is not None
    assert with_talk.state.realtime_issuer.agent_name == "story-agent"


def test_values_from_environment_like_env_example(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLE_CLIENT_IDS", "com.a.app, com.a.app.dev")
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "")
    monkeypatch.setenv("SENTRY_DSN", "")
    settings = Settings(_env_file=None)
    assert settings.apple_client_ids == ["com.a.app", "com.a.app.dev"]
    assert settings.google_client_ids == []
    assert settings.sentry_dsn is None


# ---------- logging ----------


def test_json_formatter_redacts_sensitive_keys_recursively() -> None:
    record = logging.makeLogRecord(
        {
            "name": "test",
            "levelname": "INFO",
            "msg": "event",
            "user_id": "u-1",
            "payload": {"password": "hunter2", "nested": [{"refresh_token": "abc", "count": 3}]},
            "authorization": "Bearer xyz",
            "transcript_text": "원형극장이 뭐야?",
        }
    )
    output = JsonFormatter().format(record)
    data = json.loads(output)
    assert data["user_id"] == "u-1"
    assert data["payload"]["password"] == REDACTED
    assert data["payload"]["nested"][0] == {"refresh_token": REDACTED, "count": 3}
    assert data["authorization"] == REDACTED
    assert data["transcript_text"] == REDACTED
    for secret in ("hunter2", "abc", "xyz", "원형극장"):
        assert secret not in output


# ---------- passwords ----------


def test_password_hash_roundtrip() -> None:
    hashed = passwords.hash_password_sync("pässwörd-안전")
    assert hashed.startswith("$argon2id$")
    assert passwords.verify_password_sync(hashed, "pässwörd-안전")
    assert not passwords.verify_password_sync(hashed, "wrong")
    assert not passwords.verify_password_sync(None, "anything")
    assert not passwords.verify_password_sync("not-a-hash", "anything")


# ---------- tokens ----------


def _token_service(clock: datetime | None = None) -> TokenService:
    return TokenService(
        secret=SecretStr("unit-test-secret-" + "z" * 32),
        issuer="iss",
        audience="aud",
        access_ttl=timedelta(minutes=15),
        clock=(lambda: clock) if clock else (lambda: datetime.now(UTC)),
    )


def test_access_token_roundtrip() -> None:
    service = _token_service()
    user_id = uuid.uuid4()
    token, expires_at = service.issue_access_token(user_id)
    claims = service.decode_access_token(token)
    assert claims.user_id == user_id
    assert abs((claims.expires_at - expires_at).total_seconds()) < 1


def test_expired_access_token_rejected() -> None:
    issued = _token_service(datetime.now(UTC) - timedelta(hours=1))
    token, _ = issued.issue_access_token(uuid.uuid4())
    with pytest.raises(Unauthorized):
        _token_service().decode_access_token(token)


def test_access_token_with_other_audience_or_secret_rejected() -> None:
    token, _ = _token_service().issue_access_token(uuid.uuid4())
    other_audience = TokenService(
        secret=SecretStr("unit-test-secret-" + "z" * 32),
        issuer="iss",
        audience="other",
        access_ttl=timedelta(minutes=5),
    )
    other_secret = TokenService(
        secret=SecretStr("different-secret-" + "q" * 32),
        issuer="iss",
        audience="aud",
        access_ttl=timedelta(minutes=5),
    )
    for service in (other_audience, other_secret):
        with pytest.raises(Unauthorized):
            service.decode_access_token(token)


def test_refresh_token_properties() -> None:
    token = generate_refresh_token()
    assert len(token) >= 43
    assert generate_refresh_token() != token
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert len(hash_refresh_token(token)) == 64


# ---------- rate limiting ----------


@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_fixed_window_limiter(backend: str) -> None:
    now = [1_000_000.0]
    limiter = (
        InMemoryRateLimiter(clock=lambda: now[0])
        if backend == "memory"
        else RedisRateLimiter(FakeAsyncRedis(), clock=lambda: now[0])
    )
    results = [await limiter.hit("login:ip:1.2.3.4", limit=2, window_s=60) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]
    assert 1 <= results[-1].retry_after_s <= 60

    now[0] += 60  # next window
    assert (await limiter.hit("login:ip:1.2.3.4", limit=2, window_s=60)).allowed


async def test_redis_limiter_fails_open_when_redis_is_down(tmp_path: Path) -> None:
    class BrokenRedis(FakeAsyncRedis):
        def pipeline(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise ConnectionError("redis down")

    limiter = RedisRateLimiter(BrokenRedis())
    assert (await limiter.hit("k", limit=1, window_s=60)).allowed


def _request(headers: dict[str, str], client_host: str = "10.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (client_host, 1234),
        }
    )


def test_client_ip_ignores_forwarded_header_without_trusted_proxies() -> None:
    request = _request({"X-Forwarded-For": "6.6.6.6"})
    assert client_ip(request, trusted_proxy_count=0) == "10.0.0.1"


def test_client_ip_uses_configured_proxy_hop() -> None:
    # spoofed, real client, added by our load balancer
    request = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    assert client_ip(request, trusted_proxy_count=1) == "203.0.113.9"
