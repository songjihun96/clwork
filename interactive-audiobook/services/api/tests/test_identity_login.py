import time
import uuid

import httpx
import jwt
from story_core.models.user import IdentityProvider

from tests.conftest import APPLE_CLIENT_ID, AppFactory, IdTokenFactory, auth_header, make_client, register

NONCE = "nonce-" + uuid.uuid4().hex


async def test_apple_sign_in_creates_account_then_reuses_it(
    client: httpx.AsyncClient, id_tokens: IdTokenFactory
) -> None:
    token = id_tokens.make(IdentityProvider.APPLE, subject="apple-sub-1", email_verified="true", nonce=NONCE)
    first = await client.post(
        "/v1/auth/oauth/apple", json={"id_token": token, "nonce": NONCE, "display_name": "모모"}
    )
    assert first.status_code == 200, first.text
    user = first.json()["user"]
    assert user["email"] == "social@example.com"
    assert user["display_name"] == "모모"

    token_again = id_tokens.make(IdentityProvider.APPLE, subject="apple-sub-1", nonce=NONCE)
    second = await client.post("/v1/auth/oauth/apple", json={"id_token": token_again, "nonce": NONCE})
    assert second.status_code == 200
    assert second.json()["user"]["id"] == user["id"]

    me = await client.get("/v1/users/me", headers=auth_header(second.json()["access_token"]))
    assert me.status_code == 200


async def test_google_sign_in_with_plain_nonce(client: httpx.AsyncClient, id_tokens: IdTokenFactory) -> None:
    token = id_tokens.make(IdentityProvider.GOOGLE, subject="google-sub", email="g@example.com", nonce=NONCE)
    response = await client.post("/v1/auth/oauth/google", json={"id_token": token, "nonce": NONCE})
    assert response.status_code == 200, response.text


async def test_rejects_wrong_audience_issuer_expiry_and_signature(
    client: httpx.AsyncClient, id_tokens: IdTokenFactory
) -> None:
    bad_tokens = [
        id_tokens.make(IdentityProvider.APPLE, audience="com.attacker.app"),
        id_tokens.make(IdentityProvider.APPLE, issuer="https://evil.example.com"),
        id_tokens.make(IdentityProvider.APPLE, expires_in=-3600),
        # Signed with a different key (HS256 with a guessable secret) must never be accepted.
        jwt.encode(
            {
                "iss": "https://appleid.apple.com",
                "aud": APPLE_CLIENT_ID,
                "sub": "x",
                "iat": int(time.time()),
                "exp": int(time.time()) + 600,
            },
            "public-key-confusion-secret-000000000000",
            algorithm="HS256",
        ),
    ]
    for token in bad_tokens:
        response = await client.post("/v1/auth/oauth/apple", json={"id_token": token})
        assert response.status_code == 401, token
        assert response.json()["error"]["code"] == "invalid_identity_token"


async def test_rejects_nonce_mismatch(client: httpx.AsyncClient, id_tokens: IdTokenFactory) -> None:
    token = id_tokens.make(IdentityProvider.APPLE, nonce=NONCE)
    wrong = await client.post(
        "/v1/auth/oauth/apple", json={"id_token": token, "nonce": "another-nonce-value"}
    )
    missing = await client.post("/v1/auth/oauth/apple", json={"id_token": token})
    assert wrong.status_code == missing.status_code == 401


async def test_does_not_auto_link_to_existing_email_account(
    client: httpx.AsyncClient, id_tokens: IdTokenFactory
) -> None:
    await register(client, "shared@example.com")
    token = id_tokens.make(IdentityProvider.GOOGLE, subject="g-2", email="shared@example.com")
    response = await client.post("/v1/auth/oauth/google", json={"id_token": token})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_link_required"


async def test_unverified_email_is_not_stored(client: httpx.AsyncClient, id_tokens: IdTokenFactory) -> None:
    token = id_tokens.make(
        IdentityProvider.GOOGLE, subject="g-3", email="unverified@example.com", email_verified=False
    )
    response = await client.post("/v1/auth/oauth/google", json={"id_token": token})
    assert response.status_code == 200
    assert response.json()["user"]["email"] is None


async def test_unconfigured_provider_returns_503(app_factory: AppFactory, id_tokens: IdTokenFactory) -> None:
    app = app_factory(apple_client_ids=[])
    async with await make_client(app) as client:
        token = id_tokens.make(IdentityProvider.APPLE)
        response = await client.post("/v1/auth/oauth/apple", json={"id_token": token})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_not_configured"


async def test_unknown_provider_path_is_rejected(
    client: httpx.AsyncClient, id_tokens: IdTokenFactory
) -> None:
    response = await client.post("/v1/auth/oauth/facebook", json={"id_token": "x" * 30})
    assert response.status_code == 422


async def test_social_account_deletion_requires_recent_sign_in(
    app_factory: AppFactory, id_tokens: IdTokenFactory
) -> None:
    app = app_factory()
    async with await make_client(app) as client:
        token = id_tokens.make(IdentityProvider.GOOGLE, subject="g-del")
        tokens = (await client.post("/v1/auth/oauth/google", json={"id_token": token})).json()

        # Fresh token: deletion allowed without password.
        response = await client.request(
            "DELETE", "/v1/users/me", json={}, headers=auth_header(tokens["access_token"])
        )
        assert response.status_code == 204

        # Stale token (issued before the recent-auth window) is refused.
        token2 = id_tokens.make(IdentityProvider.GOOGLE, subject="g-del-2", email="other@example.com")
        tokens2 = (await client.post("/v1/auth/oauth/google", json={"id_token": token2})).json()
        settings = app.state.settings
        stale_claims = jwt.decode(tokens2["access_token"], options={"verify_signature": False})
        stale_claims["iat"] -= settings.recent_auth_window_seconds + 60
        stale = jwt.encode(stale_claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")
        refused = await client.request("DELETE", "/v1/users/me", json={}, headers=auth_header(stale))
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "reauthentication_required"
