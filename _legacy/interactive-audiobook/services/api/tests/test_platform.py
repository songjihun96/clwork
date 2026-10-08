"""Cross-cutting behaviour: health, error envelope, headers, docs exposure."""

import logging
from pathlib import Path

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from tests.conftest import AppFactory, make_client


async def test_live_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_ready_reports_failure_without_details(app_factory: AppFactory) -> None:
    app = app_factory()

    async def broken_ping() -> bool:
        raise RedisConnectionError("connection refused to 10.0.0.5:6379")

    app.state.redis.ping = broken_ping
    async with await make_client(app) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "fail"}
    assert "10.0.0.5" not in response.text


async def test_request_id_and_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "client-supplied-id-1234"})
    assert response.headers["x-request-id"] == "client-supplied-id-1234"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"

    invalid = await client.get("/health/live", headers={"X-Request-ID": "bad id with spaces\n"})
    assert invalid.headers["x-request-id"] != "bad id with spaces\n"


async def test_request_log_uses_full_route_template(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.post("/v1/auth/oauth/google", json={"id_token": "x" * 30})
        await client.get("/v1/users/me")
        await client.get("/wp-admin/secret-probe?token=abc")
    routes = [getattr(r, "route", None) for r in caplog.records if r.name == "app.request"]
    assert routes == ["/v1/auth/oauth/{provider}", "/v1/users/me", "unmatched"]


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


async def test_docs_can_be_disabled(app_factory: AppFactory) -> None:
    # Production disables docs by default (see test_units); here the switch itself is exercised.
    app = app_factory(enable_api_docs=False)
    async with await make_client(app) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


async def test_openapi_exposes_versioned_auth_routes(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    for path in (
        "/v1/auth/register",
        "/v1/auth/login",
        "/v1/auth/refresh",
        "/v1/auth/logout",
        "/v1/auth/oauth/{provider}",
        "/v1/users/me",
    ):
        assert path in paths


async def test_api_starts_and_serves_when_redis_is_down(tmp_path: Path) -> None:
    """Regression: the job broker's startup used to abort the whole lifespan without Redis."""
    from app.main import create_app
    from tests.conftest import make_settings

    settings = make_settings(tmp_path, redis_url="redis://127.0.0.1:1/0", redis_timeout_s=0.2)
    app = create_app(settings, configure_logs=False)  # real Redis client and broker, unreachable
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.get("/health/live")).status_code == 200
            ready = await client.get("/health/ready")
            assert ready.status_code == 503 and ready.json()["checks"]["redis"] == "fail"
