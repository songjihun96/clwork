"""Narration audio through the API: pending → worker renders → signed URL → ranged download."""

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from story_core.audio.encoding import WavEncoder
from story_core.audio.pcm import from_wav
from story_core.audio.renderer import ParagraphAudioRenderer
from story_core.jobs.queue import RENDER_PARAGRAPH_AUDIO_TASK, RecordingJobQueue
from story_core.providers.tts.base import Voice
from story_core.providers.tts.fake import FakeTTSProvider

from tests.conftest import auth_header, register
from tests.test_books_reading_api import FULL_RIGHTS, make_admin, publish


async def reader_setup(app: FastAPI, client: httpx.AsyncClient) -> dict[str, Any]:
    admin = await make_admin(app, client)
    reader = auth_header((await register(client))["access_token"])
    book_id = await publish(app, client, admin)
    session = (await client.post("/v1/reading/sessions", headers=reader, json={"book_id": book_id})).json()
    detail = (await client.get(f"/v1/books/{book_id}", headers=reader)).json()
    chapter = (
        await client.get(f"/v1/books/{book_id}/chapters/{detail['chapters'][0]['id']}", headers=reader)
    ).json()
    return {
        "admin": admin,
        "reader": reader,
        "book_id": book_id,
        "session_id": session["id"],
        "paragraphs": [p["id"] for p in chapter["paragraphs"]],
    }


def render_jobs(app: FastAPI) -> list[dict[str, Any]]:
    queue: RecordingJobQueue = app.state.job_queue
    return [kwargs for task, kwargs in queue.jobs if task == RENDER_PARAGRAPH_AUDIO_TASK]


async def run_render_jobs(app: FastAPI, tts: FakeTTSProvider) -> None:
    """Plays the worker: same storage, same provider/format as the API's lookup renderer."""
    renderer = ParagraphAudioRenderer(app.state.sessionmaker, app.state.storage, tts, WavEncoder())
    for job in render_jobs(app):
        await renderer.render(uuid.UUID(job["paragraph_id"]), Voice(job["voice_id"], job["voice_version"]))
    app.state.job_queue.jobs.clear()


def relative(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}"


async def test_audio_is_queued_then_served_with_timings(app: FastAPI, client: httpx.AsyncClient) -> None:
    ctx = await reader_setup(app, client)
    endpoint = f"/v1/reading/sessions/{ctx['session_id']}/audio"
    wanted = ctx["paragraphs"][:2]

    first = await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": wanted})
    assert first.status_code == 200
    assert [i["status"] for i in first.json()["items"]] == ["pending", "pending"]
    assert first.json()["retry_after_ms"] == 1000
    assert [j["paragraph_id"] for j in render_jobs(app)] == wanted

    # Polling again before rendering finishes must not flood the queue.
    await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": wanted})
    assert len(render_jobs(app)) == 2

    tts = FakeTTSProvider()
    await run_render_jobs(app, tts)
    calls = len(tts.calls)

    ready = (await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": wanted})).json()
    assert ready["retry_after_ms"] is None
    item = ready["items"][0]
    assert item["status"] == "ready"
    audio = item["audio"]
    assert audio["format"] == "wav" and audio["duration_ms"] > 0
    assert [t["sentence_index"] for t in audio["sentence_timings"]] == [0, 1]
    assert audio["sentence_timings"][-1]["end_ms"] == audio["duration_ms"]

    downloaded = await client.get(relative(audio["url"]))
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "audio/wav"
    assert downloaded.headers["cache-control"].startswith("private, max-age=")
    assert from_wav(downloaded.content).duration_ms == audio["duration_ms"]

    ranged = await client.get(relative(audio["url"]), headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100

    # Asking again (second playback) uses the cache: no new jobs, no new synthesis.
    await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": wanted})
    assert render_jobs(app) == [] and len(tts.calls) == calls


async def test_media_links_cannot_be_forged_or_reused_after_expiry(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await reader_setup(app, client)
    endpoint = f"/v1/reading/sessions/{ctx['session_id']}/audio"
    await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": ctx["paragraphs"][:1]})
    await run_render_jobs(app, FakeTTSProvider())
    url = (
        await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": ctx["paragraphs"][:1]})
    ).json()["items"][0]["audio"]["url"]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    exp, sig = int(query["exp"][0]), query["sig"][0]

    tampered_sig = await client.get(f"{parsed.path}?exp={exp}&sig={'0' * 64}")
    extended = await client.get(f"{parsed.path}?exp={exp + 86400}&sig={sig}")
    other_object = await client.get(f"/v1/media/audio/paragraphs/00/{'0' * 64}.wav?exp={exp}&sig={sig}")
    assert tampered_sig.status_code == extended.status_code == other_object.status_code == 403
    assert tampered_sig.json()["error"]["code"] == "invalid_media_signature"

    expired_url, _ = await app.state.storage.signed_get_url(
        parsed.path.removeprefix("/v1/media/"), expires_in_s=-5
    )
    assert (await client.get(relative(expired_url))).status_code == 403
    assert (await client.get(f"/v1/media/../../etc/passwd?exp={exp}&sig={sig}")).status_code in (403, 404)
    assert (await client.get(f"{parsed.path}")).status_code == 422  # signature required


async def test_audio_access_is_scoped_to_the_session_and_licence(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ctx = await reader_setup(app, client)
    endpoint = f"/v1/reading/sessions/{ctx['session_id']}/audio"
    other_book = await publish(app, client, ctx["admin"])
    other_detail = (await client.get(f"/v1/books/{other_book}", headers=ctx["reader"])).json()
    foreign_paragraph = (
        await client.get(
            f"/v1/books/{other_book}/chapters/{other_detail['chapters'][0]['id']}", headers=ctx["reader"]
        )
    ).json()["paragraphs"][0]["id"]

    mixed = (
        await client.post(
            endpoint, headers=ctx["reader"], json={"paragraph_ids": [foreign_paragraph, str(uuid.uuid4())]}
        )
    ).json()
    assert [i["status"] for i in mixed["items"]] == ["unavailable", "unavailable"]
    assert render_jobs(app) == []

    intruder = auth_header((await register(client))["access_token"])
    denied = await client.post(endpoint, headers=intruder, json={"paragraph_ids": ctx["paragraphs"][:1]})
    assert denied.status_code == 404

    too_many = await client.post(
        endpoint, headers=ctx["reader"], json={"paragraph_ids": [str(uuid.uuid4())] * 6}
    )
    assert too_many.status_code == 422

    no_audio_rights = {**FULL_RIGHTS, "audio_rights": False}
    assert (
        await client.put(
            f"/v1/admin/books/{ctx['book_id']}/rights", headers=ctx["admin"], json=no_audio_rights
        )
    ).status_code == 200
    revoked = (
        await client.post(endpoint, headers=ctx["reader"], json={"paragraph_ids": ctx["paragraphs"][:1]})
    ).json()
    assert revoked["items"][0]["status"] == "unavailable"
