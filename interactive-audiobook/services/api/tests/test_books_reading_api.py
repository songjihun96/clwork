"""Phase 2 exit criteria through the HTTP API: upload → process → read → position restore."""

import json
from datetime import timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import update
from story_core.books.rights import rights_today
from story_core.ingestion.pipeline import ingest_book
from story_core.jobs.queue import INGEST_BOOK_TASK, RecordingJobQueue
from story_core.models import User, UserRole

from tests.conftest import TEST_PASSWORD, AppFactory, auth_header, make_client, register

SAMPLE_TXT = (
    "제1장 바람이 바뀌던 날\n\n"
    "섬의 끝에는 오래된 등대가 하나 서 있었다. 하얀 벽은 소금기에 바래 있었다.\n\n"
    "그날은 바람의 냄새가 달랐다.\n\n"
    "제2장 낮게 뜬 불빛\n\n"
    "하람은 손전등을 챙겨 바위길로 내려갔다. 파도가 발목까지 올라왔다.\n"
).encode()

FULL_RIGHTS: dict[str, Any] = {
    "rights_type": "owned",
    "rights_holder": "Interactive Audiobook (sample text)",
    "commercial_use": True,
    "audio_rights": True,
    "ai_processing_rights": True,
}


def metadata(**rights_overrides: Any) -> str:
    return json.dumps(
        {"title": "등대지기의 밤", "author": "샘플", "rights": {**FULL_RIGHTS, **rights_overrides}}
    )


async def make_admin(app: FastAPI, client: httpx.AsyncClient) -> dict[str, str]:
    account = await register(client)
    async with app.state.sessionmaker() as session:
        await session.execute(update(User).where(User.email == account["_email"]).values(role=UserRole.ADMIN))
        await session.commit()
    return auth_header(account["access_token"])


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    data: bytes = SAMPLE_TXT,
    name: str = "lighthouse.txt",
    meta: str | None = None,
) -> httpx.Response:
    return await client.post(
        "/v1/admin/books",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
        data={"metadata": meta or metadata()},
    )


async def publish(app: FastAPI, client: httpx.AsyncClient, admin: dict[str, str], **kwargs: Any) -> str:
    created = await upload(client, admin, **kwargs)
    assert created.status_code == 201, created.text
    book_id: str = created.json()["id"]
    queued = await client.post(f"/v1/admin/books/{book_id}/process", headers=admin)
    assert queued.status_code == 202, queued.text
    await run_jobs(app)
    return book_id


async def run_jobs(app: FastAPI) -> None:
    """Plays the worker's role for recorded jobs."""
    queue: RecordingJobQueue = app.state.job_queue
    while queue.jobs:
        task, kwargs = queue.jobs.pop(0)
        assert task == INGEST_BOOK_TASK
        import uuid

        await ingest_book(
            app.state.sessionmaker,
            app.state.storage,
            uuid.UUID(kwargs["book_id"]),
            expected_version=kwargs["expected_version"],
        )


# ------------------------------------------------------------------ admin


async def test_upload_requires_admin(app: FastAPI, client: httpx.AsyncClient) -> None:
    reader = auth_header((await register(client))["access_token"])
    assert (await upload(client, reader)).status_code == 403
    assert (await client.post("/v1/admin/books", files={"file": ("a.txt", b"x")})).status_code == 401


async def test_upload_validation(app_factory: AppFactory) -> None:
    app = app_factory(book_upload_max_bytes=2048)
    async with await make_client(app) as client:
        admin = await make_admin(app, client)

        bad_meta = await upload(client, admin, meta=json.dumps({"title": "", "rights": FULL_RIGHTS}))
        assert bad_meta.status_code == 422
        assert bad_meta.json()["error"]["details"][0]["loc"][:2] == ["body", "metadata"]

        backwards = await upload(
            client, admin, meta=metadata(license_start="2026-01-01", license_end="2025-01-01")
        )
        assert backwards.status_code == 422

        png = await upload(client, admin, data=b"\x89PNG\r\n\x1a\n" + b"0" * 100, name="cover.png")
        assert (png.status_code, png.json()["error"]["code"]) == (415, "unsupported_file_type")

        cp949 = await upload(client, admin, data="등대지기".encode("cp949"), name="book.txt")
        assert cp949.status_code == 415

        huge = await upload(client, admin, data=b"a" * 5000, name="big.txt")
        assert (huge.status_code, huge.json()["error"]["code"]) == (413, "file_too_large")


async def test_rights_gate_blocks_processing_until_fixed(app: FastAPI, client: httpx.AsyncClient) -> None:
    admin = await make_admin(app, client)
    created = await upload(client, admin, meta=metadata(audio_rights=False, ai_processing_rights=False))
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "uploaded"
    assert set(body["rights_problems"]) == {"audio_rights_missing", "ai_processing_rights_missing"}

    refused = await client.post(f"/v1/admin/books/{body['id']}/process", headers=admin)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "rights_insufficient")
    assert app.state.job_queue.jobs == []

    fixed = await client.put(f"/v1/admin/books/{body['id']}/rights", headers=admin, json=FULL_RIGHTS)
    assert fixed.status_code == 200 and fixed.json()["rights_problems"] == []

    queued = await client.post(f"/v1/admin/books/{body['id']}/process", headers=admin)
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    assert app.state.job_queue.jobs == [(INGEST_BOOK_TASK, {"book_id": body["id"], "expected_version": 0})]

    await run_jobs(app)
    status = await client.get(f"/v1/admin/books/{body['id']}", headers=admin)
    assert status.json()["status"] == "ready"
    assert status.json()["total_sentences"] == 5


async def test_epub_upload_is_detected_by_content(app: FastAPI, client: httpx.AsyncClient) -> None:
    from tests.epub_fixture import SAMPLE_EPUB

    admin = await make_admin(app, client)
    # Misleading name: detection uses the bytes, not the extension.
    book_id = await publish(app, client, admin, data=SAMPLE_EPUB, name="book.txt")
    detail = await client.get(f"/v1/admin/books/{book_id}", headers=admin)
    assert detail.json()["source_format"] == "epub" and detail.json()["status"] == "ready"


# ------------------------------------------------------------------ reader


async def test_reader_sees_only_ready_licensed_books(app: FastAPI, client: httpx.AsyncClient) -> None:
    admin = await make_admin(app, client)
    reader = auth_header((await register(client))["access_token"])
    ready_id = await publish(app, client, admin)
    unprocessed = (await upload(client, admin)).json()["id"]

    listing = (await client.get("/v1/books", headers=reader)).json()
    assert [b["id"] for b in listing["items"]] == [ready_id] and listing["total"] == 1

    assert (await client.get(f"/v1/books/{unprocessed}", headers=reader)).status_code == 404

    expired = {
        **FULL_RIGHTS,
        "license_end": (rights_today() - timedelta(days=1)).isoformat(),
        "license_start": "2020-01-01",
    }
    assert (
        await client.put(f"/v1/admin/books/{ready_id}/rights", headers=admin, json=expired)
    ).status_code == 200
    assert (await client.get(f"/v1/books/{ready_id}", headers=reader)).status_code == 404
    assert (await client.get("/v1/books", headers=reader)).json()["items"] == []


async def test_book_detail_and_chapter_content(app: FastAPI, client: httpx.AsyncClient) -> None:
    admin = await make_admin(app, client)
    reader = auth_header((await register(client))["access_token"])
    book_id = await publish(app, client, admin)

    detail = (await client.get(f"/v1/books/{book_id}", headers=reader)).json()
    assert [c["title"] for c in detail["chapters"]] == ["제1장 바람이 바뀌던 날", "제2장 낮게 뜬 불빛"]
    assert [(c["first_sentence_seq"], c["sentence_count"]) for c in detail["chapters"]] == [(0, 3), (3, 2)]

    chapter = (
        await client.get(f"/v1/books/{book_id}/chapters/{detail['chapters'][0]['id']}", headers=reader)
    ).json()
    assert [p["sentences"] for p in chapter["paragraphs"]] == [
        ["섬의 끝에는 오래된 등대가 하나 서 있었다.", "하얀 벽은 소금기에 바래 있었다."],
        ["그날은 바람의 냄새가 달랐다."],
    ]
    assert [p["first_sentence_seq"] for p in chapter["paragraphs"]] == [0, 2]

    other_chapter = detail["chapters"][1]["id"]
    wrong_book = await publish(app, client, admin)
    assert (
        await client.get(f"/v1/books/{wrong_book}/chapters/{other_chapter}", headers=reader)
    ).status_code == 404


# ------------------------------------------------------------------ reading sessions


async def test_reading_session_lifecycle_and_restore_after_restart(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    admin = await make_admin(app, client)
    account = await register(client)
    reader = auth_header(account["access_token"])
    book_id = await publish(app, client, admin)

    opened = await client.post("/v1/reading/sessions", headers=reader, json={"book_id": book_id})
    assert opened.status_code == 201
    session = opened.json()
    assert session["playback_state"] == "IDLE" and session["position"]["sentence_global_seq"] == 0
    again = await client.post("/v1/reading/sessions", headers=reader, json={"book_id": book_id})
    assert again.status_code == 200 and again.json()["id"] == session["id"]

    detail = (await client.get(f"/v1/books/{book_id}", headers=reader)).json()
    chapter2 = (
        await client.get(f"/v1/books/{book_id}/chapters/{detail['chapters'][1]['id']}", headers=reader)
    ).json()
    target = chapter2["paragraphs"][0]

    moved = await client.patch(
        f"/v1/reading/sessions/{session['id']}",
        headers={**reader, "X-Device-Id": "phone-aaaa-1111"},
        json={"position": {"paragraph_id": target["id"], "sentence_index": 0, "expected_version": 1}},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["position"]["sentence_global_seq"] == 3
    assert moved.json()["position"]["chapter_id"] == detail["chapters"][1]["id"]
    assert moved.json()["progress"] == 4 / 5

    stale = await client.patch(
        f"/v1/reading/sessions/{session['id']}",
        headers=reader,
        json={"position": {"paragraph_id": target["id"], "sentence_index": 1, "expected_version": 1}},
    )
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "position_conflict")

    invalid = await client.patch(
        f"/v1/reading/sessions/{session['id']}",
        headers=reader,
        json={"position": {"paragraph_id": target["id"], "sentence_index": 7, "expected_version": 2}},
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "invalid_position")

    played = await client.post(
        f"/v1/reading/sessions/{session['id']}/playback", headers=reader, json={"action": "play"}
    )
    assert played.json()["playback_state"] == "READING"

    # "Force quit": a brand-new client signs in again and restores exactly the same sentence.
    async with await_fresh_client(app) as restarted:
        login = await restarted.post(
            "/v1/auth/login", json={"email": account["_email"], "password": TEST_PASSWORD}
        )
        fresh = auth_header(login.json()["access_token"])
        sessions = (await restarted.get("/v1/reading/sessions", headers=fresh)).json()["items"]
        assert len(sessions) == 1
        restored = sessions[0]
        assert restored["id"] == session["id"]
        assert restored["position"]["paragraph_id"] == target["id"]
        assert restored["position"]["sentence_index"] == 0
        assert restored["position"]["position_version"] == 2
        assert restored["book"]["title"] == "등대지기의 밤"


def await_fresh_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_sessions_are_private_and_validated(app: FastAPI, client: httpx.AsyncClient) -> None:
    admin = await make_admin(app, client)
    owner = auth_header((await register(client))["access_token"])
    intruder = auth_header((await register(client))["access_token"])
    book_id = await publish(app, client, admin)
    session_id = (await client.post("/v1/reading/sessions", headers=owner, json={"book_id": book_id})).json()[
        "id"
    ]

    assert (await client.get(f"/v1/reading/sessions/{session_id}", headers=intruder)).status_code == 404
    patch = await client.patch(f"/v1/reading/sessions/{session_id}", headers=intruder, json={"speed": 1.5})
    assert patch.status_code == 404
    assert (await client.get("/v1/reading/sessions", headers=intruder)).json()["items"] == []

    assert (
        await client.patch(f"/v1/reading/sessions/{session_id}", headers=owner, json={})
    ).status_code == 422
    too_fast = await client.patch(f"/v1/reading/sessions/{session_id}", headers=owner, json={"speed": 9})
    assert too_fast.status_code == 422
    settings = await client.patch(
        f"/v1/reading/sessions/{session_id}",
        headers=owner,
        json={"speed": 1.25, "spoiler_mode": "LIGHT_SPOILER"},
    )
    assert settings.json()["speed"] == 1.25 and settings.json()["spoiler_mode"] == "LIGHT_SPOILER"

    rejected = await client.post(
        f"/v1/reading/sessions/{session_id}/playback", headers=owner, json={"action": "pause"}
    )
    assert (rejected.status_code, rejected.json()["error"]["code"]) == (409, "playback_action_rejected")

    unknown_book = await client.post(
        "/v1/reading/sessions", headers=owner, json={"book_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert unknown_book.status_code == 404
