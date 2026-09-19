import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from story_core.models import AuditLog, RefreshToken

from tests.conftest import TEST_PASSWORD, AppFactory, auth_header, make_client, register


async def test_register_returns_tokens_and_user(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "Reader@Example.com", "password": TEST_PASSWORD, "display_name": "독자"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "reader@example.com"  # normalised
    assert body["user"]["display_name"] == "독자"
    assert "password_hash" not in body["user"]

    me = await client.get("/v1/users/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


async def test_register_duplicate_email_conflicts_case_insensitively(client: httpx.AsyncClient) -> None:
    await register(client, "dup@example.com")
    response = await client.post(
        "/v1/auth/register", json={"email": "DUP@example.com", "password": TEST_PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_validation_error_does_not_echo_password(client: httpx.AsyncClient) -> None:
    secret = "Qz7#kW"  # too short, and unlikely to appear in any error text by coincidence
    response = await client.post("/v1/auth/register", json={"email": "not-an-email", "password": secret})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert secret not in response.text
    assert body["error"]["request_id"]


async def test_unknown_fields_are_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/register", json={"email": "a@example.com", "password": TEST_PASSWORD, "is_admin": True}
    )
    assert response.status_code == 422


async def test_login_success_and_uniform_failure(client: httpx.AsyncClient) -> None:
    account = await register(client)

    ok = await client.post("/v1/auth/login", json={"email": account["_email"], "password": TEST_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["user"]["id"] == account["user"]["id"]

    wrong_password = await client.post(
        "/v1/auth/login", json={"email": account["_email"], "password": "nope-nope"}
    )
    unknown_email = await client.post(
        "/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same code and message: the response must not reveal whether the account exists.
    assert (
        wrong_password.json()["error"]["code"]
        == unknown_email.json()["error"]["code"]
        == "invalid_credentials"
    )
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_refresh_rotates_and_detects_reuse(client: httpx.AsyncClient) -> None:
    account = await register(client)
    first_refresh = account["refresh_token"]

    rotated = await client.post("/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    second_refresh = rotated.json()["refresh_token"]
    assert second_refresh != first_refresh

    # Replaying the rotated token revokes the whole family, including the newest token.
    replay = await client.post("/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_token_reused"

    after_reuse = await client.post("/v1/auth/refresh", json={"refresh_token": second_refresh})
    assert after_reuse.status_code == 401


async def test_refresh_with_unknown_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/auth/refresh", json={"refresh_token": "x" * 43})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_logout_revokes_refresh_token_and_is_idempotent(client: httpx.AsyncClient) -> None:
    account = await register(client)
    assert (
        await client.post("/v1/auth/logout", json={"refresh_token": account["refresh_token"]})
    ).status_code == 204
    assert (
        await client.post("/v1/auth/logout", json={"refresh_token": account["refresh_token"]})
    ).status_code == 204
    refresh = await client.post("/v1/auth/refresh", json={"refresh_token": account["refresh_token"]})
    assert refresh.status_code == 401


async def test_me_requires_valid_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/users/me")).status_code == 401
    assert (await client.get("/v1/users/me", headers=auth_header("not.a.jwt"))).status_code == 401

    account = await register(client)
    header, payload, signature = account["access_token"].split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}AA"
    assert (await client.get("/v1/users/me", headers=auth_header(tampered))).status_code == 401


async def test_refresh_token_is_stored_hashed(app: FastAPI, client: httpx.AsyncClient) -> None:
    account = await register(client)
    async with app.state.sessionmaker() as session:
        hashes = (await session.execute(select(RefreshToken.token_hash))).scalars().all()
    assert account["refresh_token"] not in hashes
    assert all(len(h) == 64 for h in hashes)


async def test_login_rate_limit_per_account(app_factory: AppFactory) -> None:
    app = app_factory(rate_limit_login_per_account=3, rate_limit_login_per_ip=100)
    async with await make_client(app) as client:
        account = await register(client)
        statuses = [
            (
                await client.post(
                    "/v1/auth/login", json={"email": account["_email"], "password": "wrong-pass"}
                )
            ).status_code
            for _ in range(4)
        ]
        assert statuses == [401, 401, 401, 429]
        blocked = await client.post(
            "/v1/auth/login", json={"email": account["_email"], "password": TEST_PASSWORD}
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1


async def test_register_rate_limit_per_ip(app_factory: AppFactory) -> None:
    app = app_factory(rate_limit_register_per_ip=2)
    async with await make_client(app) as client:
        await register(client)
        await register(client)
        response = await client.post(
            "/v1/auth/register", json={"email": "third@example.com", "password": TEST_PASSWORD}
        )
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"


async def test_login_attempts_are_audited_without_email(app: FastAPI, client: httpx.AsyncClient) -> None:
    account = await register(client)
    await client.post("/v1/auth/login", json={"email": account["_email"], "password": "wrong-pass"})
    async with app.state.sessionmaker() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    actions = [r.action for r in rows]
    assert "user.registered" in actions
    assert "auth.login_failed" in actions
    assert account["_email"] not in str([(r.details, r.target_id) for r in rows])


async def test_account_deletion_requires_password_and_cascades(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    account = await register(client)
    headers = auth_header(account["access_token"])
    user_id = account["user"]["id"]

    missing = await client.request("DELETE", "/v1/users/me", json={}, headers=headers)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "reauthentication_required"

    deleted = await client.request(
        "DELETE", "/v1/users/me", json={"password": TEST_PASSWORD}, headers=headers
    )
    assert deleted.status_code == 204

    assert (await client.get("/v1/users/me", headers=headers)).status_code == 401
    relogin = await client.post(
        "/v1/auth/login", json={"email": account["_email"], "password": TEST_PASSWORD}
    )
    assert relogin.status_code == 401

    async with app.state.sessionmaker() as session:
        tokens_left = await session.scalar(select(func.count()).select_from(RefreshToken))
        audit = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "user.deleted"))).scalars().all()
        )
    assert tokens_left == 0  # ON DELETE CASCADE
    assert len(audit) == 1 and str(audit[0].actor_user_id) == user_id  # audit survives deletion
