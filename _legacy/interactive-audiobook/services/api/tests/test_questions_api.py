"""Questions through the API: grounded answers, spoiler window, rights, rate limit, ownership."""

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from story_core.models import BookRights, ConversationMessage, ReadingPosition, ReadingSession
from story_core.providers.llm.fake import FakeLLMProvider
from story_core.rag.index import ChunkIndexer
from story_core.rag.spoiler import SAFE_ANSWER

from tests.conftest import auth_header, register
from tests.test_books_reading_api import make_admin, publish


async def ask_setup(app: FastAPI, client: httpx.AsyncClient) -> dict[str, Any]:
    admin = await make_admin(app, client)
    account = await register(client)
    reader = auth_header(account["access_token"])
    book_id = await publish(app, client, admin)
    # The worker's embedding step, run inline with the app's own embedder.
    indexer = ChunkIndexer(app.state.sessionmaker, app.state.embedder)
    outcome = await indexer.index_book(uuid.UUID(book_id))
    assert outcome.status == "ready", outcome
    session = (await client.post("/v1/reading/sessions", headers=reader, json={"book_id": book_id})).json()
    return {"admin": admin, "reader": reader, "book_id": book_id, "session_id": session["id"]}


async def advance(app: FastAPI, session_id: str, *, seq: int) -> None:
    """Move the reader forward (narration does this in the app)."""
    async with app.state.sessionmaker() as db:
        await db.execute(
            update(ReadingPosition)
            .where(ReadingPosition.session_id == uuid.UUID(session_id))
            .values(sentence_global_seq=seq)
        )
        await db.execute(
            update(ReadingSession).where(ReadingSession.id == uuid.UUID(session_id)).values(max_read_seq=seq)
        )
        await db.commit()


async def test_question_is_answered_from_the_book_and_recorded(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await ask_setup(app, client)
    await advance(app, ctx["session_id"], seq=4)

    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions",
        headers=ctx["reader"],
        json={"text": "하람은 무엇을 하고 있었어?"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]
    assert body["grounded"] is True
    assert body["citations"] and all(
        c["end_global_seq"] <= body["allowed_global_seq"] for c in body["citations"]
    )
    assert body["allowed_global_seq"] == 4
    assert body["spoiler_mode"] == "NO_SPOILER"
    assert body["latency_ms"]["total"] >= 0

    async with app.state.sessionmaker() as db:
        roles = (
            await db.execute(
                select(ConversationMessage.role, ConversationMessage.text).order_by(ConversationMessage.role)
            )
        ).all()
    assert [row.role for row in roles] == ["assistant", "user"]
    assert any("하람" in row.text for row in roles)


async def test_answer_never_uses_text_the_reader_has_not_heard(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await ask_setup(app, client)
    await advance(app, ctx["session_id"], seq=1)

    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions",
        headers=ctx["reader"],
        json={"text": "하람이 바위길에서 무엇을 외쳤어?"},  # happens in a later chapter
    )

    body = response.json()
    assert response.status_code == 200
    assert body["allowed_global_seq"] == 1
    assert all(c["end_global_seq"] <= 1 for c in body["citations"])
    assert "누구 있어요" not in body["answer"]


async def test_a_leaked_future_name_is_replaced_by_the_safe_answer(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await ask_setup(app, client)
    # The model answers with a sentence from a part the reader has not reached.
    app.state.llm = FakeLLMProvider(responses=["하람이 바위길로 내려갔어요."])

    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions",
        headers=ctx["reader"],
        json={"text": "앞으로 무슨 일이 생겨?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == SAFE_ANSWER and body["grounded"] is False


async def test_questions_require_ai_processing_rights(app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await ask_setup(app, client)
    async with app.state.sessionmaker() as db:
        await db.execute(
            update(BookRights)
            .where(BookRights.book_id == uuid.UUID(ctx["book_id"]))
            .values(ai_processing_rights=False)
        )
        await db.commit()

    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions",
        headers=ctx["reader"],
        json={"text": "하람은 누구야?"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "book_unavailable"


async def test_another_users_session_is_not_found(app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await ask_setup(app, client)
    intruder = auth_header((await register(client))["access_token"])

    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions",
        headers=intruder,
        json={"text": "하람은 누구야?"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "가" * 501}, {"text": "야", "extra": 1}])
async def test_invalid_payloads_are_rejected(
    app: FastAPI, client: httpx.AsyncClient, payload: dict[str, Any]
) -> None:
    ctx = await ask_setup(app, client)
    response = await client.post(
        f"/v1/reading/sessions/{ctx['session_id']}/questions", headers=ctx["reader"], json=payload
    )
    assert response.status_code == 422


async def test_questions_are_rate_limited_per_account(app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await ask_setup(app, client)
    app.state.settings.rate_limit_enabled = True
    app.state.settings.question_rate_limit_per_minute = 2
    endpoint = f"/v1/reading/sessions/{ctx['session_id']}/questions"
    try:
        for _ in range(2):
            ok = await client.post(endpoint, headers=ctx["reader"], json={"text": "하람은 누구야?"})
            assert ok.status_code == 200, ok.text
        limited = await client.post(endpoint, headers=ctx["reader"], json={"text": "하람은 누구야?"})
        assert limited.status_code == 429
        assert limited.headers["retry-after"]

        # A different account is unaffected: the limit follows the account, not the address.
        other = auth_header((await register(client))["access_token"])
        other_session = (
            await client.post("/v1/reading/sessions", headers=other, json={"book_id": ctx["book_id"]})
        ).json()
        allowed = await client.post(
            f"/v1/reading/sessions/{other_session['id']}/questions",
            headers=other,
            json={"text": "하람은 누구야?"},
        )
        assert allowed.status_code == 200
    finally:
        app.state.settings.rate_limit_enabled = False
