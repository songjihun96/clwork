"""Talk-mode tokens: least privilege, ownership, rights, availability, rate limit.

The token is a bearer credential for a media server, so the grants are asserted field by field. A widened
grant would not fail any other test — it would just quietly let a leaked token do more.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from story_core.models import BookRights

from app.security.realtime import RealtimeConfig, RealtimeTokenIssuer
from tests.conftest import auth_header, register
from tests.test_books_reading_api import make_admin, publish

SECRET = "secret" * 8
CONFIG = RealtimeConfig(
    url="ws://127.0.0.1:7880", api_key="devkey", api_secret=SECRET, agent_name="story-agent"
)


def claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_aud": False})


async def talk_setup(app: FastAPI, client: httpx.AsyncClient) -> dict[str, Any]:
    admin = await make_admin(app, client)
    reader = auth_header((await register(client))["access_token"])
    book_id = await publish(app, client, admin)
    session = (await client.post("/v1/reading/sessions", headers=reader, json={"book_id": book_id})).json()
    return {"reader": reader, "book_id": book_id, "session_id": session["id"]}


@pytest.fixture
def talk_app(app: FastAPI) -> FastAPI:
    """The default app with Talk mode switched on (create_app wiring is covered in test_units)."""
    app.state.realtime_issuer = RealtimeTokenIssuer(CONFIG)
    return app


async def test_token_grants_are_least_privilege(talk_app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await talk_setup(talk_app, client)

    response = await client.post(
        "/v1/realtime/token", headers=ctx["reader"], json={"session_id": ctx["session_id"]}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"] == CONFIG.url
    assert body["room"] == f"rs_{ctx['session_id']}"
    assert body["protocol"] == "story.v1" and body["agent_name"] == "story-agent"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)

    decoded = claims(body["token"])
    video = decoded["video"]
    assert decoded["sub"] == body["identity"] and body["identity"].startswith("u_")
    assert video["room"] == body["room"] and video["roomJoin"] is True
    # The reader may speak and send control messages — nothing else.
    assert video["canPublish"] is True and video["canSubscribe"] is True
    assert video["canPublishData"] is True
    assert video["canPublishSources"] == ["microphone"]
    for forbidden in ("roomAdmin", "roomCreate", "roomList", "roomRecord", "recorder", "hidden", "agent"):
        assert video.get(forbidden, False) is False, forbidden
    # Metadata carries the session id only: no user id, no plan, no position.
    assert json.loads(decoded["metadata"]) == {"session_id": ctx["session_id"]}
    # LiveKit tokens carry nbf/exp (no iat): the life of the credential is 10 minutes.
    assert decoded["exp"] - decoded["nbf"] == 600

    # Explicit agent dispatch, and a room that only fits the reader and the agent.
    room_config = decoded["roomConfig"]
    assert [a["agentName"] for a in room_config["agents"]] == ["story-agent"]
    assert room_config["maxParticipants"] == 2
    assert int(room_config["emptyTimeout"]) == 60


async def test_token_is_refused_for_another_users_session(
    talk_app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await talk_setup(talk_app, client)
    intruder = auth_header((await register(client))["access_token"])

    response = await client.post(
        "/v1/realtime/token", headers=intruder, json={"session_id": ctx["session_id"]}
    )

    assert response.status_code == 404


async def test_token_requires_current_rights(talk_app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await talk_setup(talk_app, client)
    async with talk_app.state.sessionmaker() as db:
        await db.execute(
            update(BookRights)
            .where(BookRights.book_id == uuid.UUID(ctx["book_id"]))
            .values(ai_processing_rights=False)
        )
        await db.commit()

    response = await client.post(
        "/v1/realtime/token", headers=ctx["reader"], json={"session_id": ctx["session_id"]}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "book_unavailable"


async def test_unknown_session_is_not_found(talk_app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await talk_setup(talk_app, client)
    response = await client.post(
        "/v1/realtime/token", headers=ctx["reader"], json={"session_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404


@pytest.mark.parametrize("payload", [{}, {"session_id": "nope"}, {"session_id": str(uuid.uuid4()), "x": 1}])
async def test_invalid_payloads_are_rejected(
    talk_app: FastAPI, client: httpx.AsyncClient, payload: dict[str, Any]
) -> None:
    ctx = await talk_setup(talk_app, client)
    response = await client.post("/v1/realtime/token", headers=ctx["reader"], json=payload)
    assert response.status_code == 422


async def test_talk_mode_is_unavailable_without_livekit_configuration(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Listen mode must keep working when LiveKit is not configured — the endpoint says so clearly."""
    ctx = await talk_setup(app, client)

    response = await client.post(
        "/v1/realtime/token", headers=ctx["reader"], json={"session_id": ctx["session_id"]}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "realtime_unavailable"


async def test_tokens_are_rate_limited_per_account(talk_app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await talk_setup(talk_app, client)
    talk_app.state.settings.rate_limit_enabled = True
    talk_app.state.settings.realtime_rate_limit_per_minute = 2
    try:
        for _ in range(2):
            ok = await client.post(
                "/v1/realtime/token", headers=ctx["reader"], json={"session_id": ctx["session_id"]}
            )
            assert ok.status_code == 200, ok.text
        limited = await client.post(
            "/v1/realtime/token", headers=ctx["reader"], json={"session_id": ctx["session_id"]}
        )
        assert limited.status_code == 429 and limited.headers["retry-after"]
    finally:
        talk_app.state.settings.rate_limit_enabled = False
