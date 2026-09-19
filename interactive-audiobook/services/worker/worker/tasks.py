"""Task registration, separated from process wiring so tests can use an in-memory broker."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from story_core.audio.renderer import AudioUnavailable, ParagraphAudioRenderer
from story_core.ingestion.pipeline import ingest_book
from story_core.jobs.queue import EMBED_BOOK_TASK, INGEST_BOOK_TASK, RENDER_PARAGRAPH_AUDIO_TASK
from story_core.providers.tts.base import Voice
from story_core.rag.index import ChunkIndexer
from story_core.storage.base import StorageProvider
from taskiq import AsyncBroker


@dataclass(frozen=True, slots=True)
class WorkerResources:
    sessionmaker: async_sessionmaker[AsyncSession]
    storage: StorageProvider
    audio_renderer: ParagraphAudioRenderer | None = None
    chunk_indexer: ChunkIndexer | None = None


def register_tasks(broker: AsyncBroker, resources: Callable[[], WorkerResources]) -> None:
    @broker.task(task_name=INGEST_BOOK_TASK, retry_on_error=True, max_retries=3, timeout=15 * 60)
    async def ingest(book_id: str, expected_version: int) -> dict[str, Any]:
        res = resources()
        outcome = await ingest_book(
            res.sessionmaker, res.storage, uuid.UUID(book_id), expected_version=expected_version
        )
        # Ingestion and embedding are separate jobs: re-embedding must be possible (new model, tuned
        # chunking) without re-parsing, and a provider outage must not roll back a parsed book.
        if outcome.status == "ready":
            await embed_book.kiq(str(book_id), expected_version + 1)
        # Expected failures (bad file, missing rights) are recorded on the book and not retried.
        return {"status": outcome.status, "error": outcome.error, "sentences": outcome.sentences}

    @broker.task(task_name=EMBED_BOOK_TASK, retry_on_error=True, max_retries=3, timeout=30 * 60)
    async def embed_book(book_id: str, expected_version: int) -> dict[str, Any]:
        indexer = resources().chunk_indexer
        if indexer is None:
            raise RuntimeError("chunk indexer is not configured")
        outcome = await indexer.index_book(uuid.UUID(book_id), expected_version=expected_version)
        return {
            "status": outcome.status,
            "error": outcome.error,
            "chunks": outcome.chunks,
            "embedded": outcome.embedded,
        }

    @broker.task(task_name=RENDER_PARAGRAPH_AUDIO_TASK, retry_on_error=True, max_retries=3, timeout=5 * 60)
    async def render_paragraph_audio(paragraph_id: str, voice_id: str, voice_version: str) -> dict[str, Any]:
        renderer = resources().audio_renderer
        if renderer is None:
            raise RuntimeError("audio renderer is not configured")
        try:
            asset = await renderer.render(uuid.UUID(paragraph_id), Voice(voice_id, voice_version))
        except AudioUnavailable:
            # Paragraph gone (reprocessed) or licence lapsed: nothing to retry.
            return {"status": "unavailable"}
        return {"status": "ready", "asset_id": str(asset.id), "duration_ms": asset.duration_ms}
