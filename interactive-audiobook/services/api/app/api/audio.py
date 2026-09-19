"""Narration audio for a reading session: returns signed URLs for cached paragraphs, queues the rest."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from story_core.audio.renderer import ParagraphAudioRenderer
from story_core.jobs.queue import RENDER_PARAGRAPH_AUDIO_TASK
from story_core.providers.tts.base import Voice
from story_core.reading.sessions import ReadingSessionService

from app.core.errors import ServiceUnavailable
from app.dependencies import CurrentUserDep, DbSession, JobQueueDep, SettingsDep, StorageDep
from app.schemas.audio import AudioFile, ParagraphAudioItem, ParagraphAudioRequest, ParagraphAudioResponse
from app.schemas.common import ERROR_RESPONSES, ErrorResponse

router = APIRouter(prefix="/reading/sessions", tags=["audio"])
logger = logging.getLogger(__name__)

_RETRY_AFTER_MS = 1000
_ENQUEUE_DEDUPE_SECONDS = 60


def get_renderer(request: Request) -> ParagraphAudioRenderer:
    return cast(ParagraphAudioRenderer, request.app.state.audio_renderer)


async def _first_request(redis: Redis, cache_key: str) -> bool:
    """Clients poll while audio renders; enqueue each paragraph at most once per minute."""
    try:
        return bool(await redis.set(f"audio:enqueued:{cache_key}", "1", nx=True, ex=_ENQUEUE_DEDUPE_SECONDS))
    except (RedisError, OSError, TimeoutError):
        return True  # fail open: a duplicate job is harmless (rendering is idempotent)


@router.post(
    "/{session_id}/audio",
    response_model=ParagraphAudioResponse,
    responses={**ERROR_RESPONSES, 404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def paragraph_audio(
    session_id: uuid.UUID,
    body: ParagraphAudioRequest,
    request: Request,
    current: CurrentUserDep,
    session: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    jobs: JobQueueDep,
    renderer: Annotated[ParagraphAudioRenderer, Depends(get_renderer)],
) -> ParagraphAudioResponse:
    view = await ReadingSessionService(session).get(current.user.id, session_id)
    # Personal voices (voice_profile_id) arrive in Phase 10.
    voice = Voice(settings.tts_default_voice)
    requested = list(dict.fromkeys(body.paragraph_ids))
    found = await renderer.lookup(requested, voice)
    redis = cast(Redis, request.app.state.redis)

    items: list[ParagraphAudioItem] = []
    pending = False
    for paragraph_id in requested:
        entry = found.get(paragraph_id)
        if entry is None or entry[0].book_id != view.session.book_id:
            items.append(ParagraphAudioItem(paragraph_id=paragraph_id, status="unavailable"))
            continue
        planned, asset = entry
        if asset is not None:
            url, expires_at = await storage.signed_get_url(
                asset.storage_key, expires_in_s=settings.media_url_ttl_seconds
            )
            items.append(
                ParagraphAudioItem(
                    paragraph_id=paragraph_id,
                    status="ready",
                    audio=AudioFile(
                        url=url,
                        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
                        format="aac" if asset.format == "aac" else "wav",
                        duration_ms=asset.duration_ms,
                        sentence_timings=asset.timings or [],
                    ),
                )
            )
            continue
        pending = True
        items.append(ParagraphAudioItem(paragraph_id=paragraph_id, status="pending"))
        if await _first_request(redis, planned.cache_key):
            try:
                await jobs.enqueue(
                    RENDER_PARAGRAPH_AUDIO_TASK,
                    paragraph_id=str(paragraph_id),
                    voice_id=voice.voice_id,
                    voice_version=voice.version,
                )
            except Exception as exc:
                logger.error("audio_enqueue_failed", extra={"exc_type": type(exc).__name__})
                raise ServiceUnavailable(
                    "Audio rendering is temporarily unavailable", code="queue_unavailable"
                ) from exc

    return ParagraphAudioResponse(items=items, retry_after_ms=_RETRY_AFTER_MS if pending else None)
