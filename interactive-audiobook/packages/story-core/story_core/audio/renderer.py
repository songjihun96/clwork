"""Paragraph narration rendering with sentence-level caching.

Each sentence is synthesized once per (provider, model, voice, parameters, text) and cached as PCM.
A paragraph file is the concatenation of its sentence clips, so sentence timestamps are exact and
independent of whether the provider reports timing. Speed is applied by the player, not synthesized,
so playback speed never splits the cache.

Idempotent and safe to run concurrently: storage keys are content-addressed and rows are inserted with
ON CONFLICT DO NOTHING (two workers may occasionally synthesize the same sentence; they never corrupt).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Table, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from story_core.audio.cache_keys import (
    paragraph_cache_key,
    paragraph_storage_key,
    sentence_cache_key,
    sentence_storage_key,
    text_hash,
)
from story_core.audio.encoding import AudioEncoder
from story_core.audio.pcm import PcmAudio, from_wav, to_wav
from story_core.books.catalog import readable_condition
from story_core.books.rights import rights_today
from story_core.models.audio import AudioAsset, AudioKind
from story_core.models.book import Book, BookRights, Paragraph, Sentence
from story_core.providers.tts.base import TTSProvider, TTSRequest, Voice
from story_core.storage.base import ObjectNotFound, StorageProvider
from story_core.time import utcnow

logger = logging.getLogger(__name__)


class AudioUnavailable(Exception):
    """Paragraph missing, or its book is not currently licensed for audio."""


@dataclass(frozen=True, slots=True)
class PlannedParagraph:
    paragraph_id: uuid.UUID
    book_id: uuid.UUID
    sentence_texts: list[str]
    sentence_keys: list[str]
    cache_key: str


class ParagraphAudioRenderer:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageProvider,
        tts: TTSProvider,
        encoder: AudioEncoder | None,
        *,
        audio_format: str | None = None,
        language: str = "ko-KR",
    ) -> None:
        """``encoder=None`` gives a lookup-only renderer (the API): it computes the same cache keys as the
        worker without needing ffmpeg, and ``render`` is unavailable."""
        if encoder is None and audio_format is None:
            raise ValueError("audio_format is required when no encoder is given")
        self._sessionmaker = sessionmaker
        self._storage = storage
        self._tts = tts
        self._encoder = encoder
        self._format = encoder.format_name if encoder is not None else str(audio_format)
        self._language = language

    # ------------------------------------------------------------------ planning / lookup

    def _request(self, text: str, voice: Voice) -> TTSRequest:
        return TTSRequest(text=text, voice=voice, language=self._language, speed=1.0)

    async def plan(
        self, session: AsyncSession, paragraph_ids: Sequence[uuid.UUID], voice: Voice
    ) -> list[PlannedParagraph]:
        """Cache keys for readable paragraphs, in the given order (unknown or unlicensed ids are skipped)."""
        if not paragraph_ids:
            return []
        readable = await session.execute(
            select(Paragraph.id, Paragraph.book_id)
            .join(Book, Book.id == Paragraph.book_id)
            .join(BookRights, BookRights.book_id == Book.id)
            .where(Paragraph.id.in_(paragraph_ids), readable_condition(rights_today()))
        )
        books: dict[uuid.UUID, uuid.UUID] = {row[0]: row[1] for row in readable.all()}
        rows = await session.execute(
            select(Sentence.paragraph_id, Sentence.text)
            .where(Sentence.paragraph_id.in_(list(books)))
            .order_by(Sentence.paragraph_id, Sentence.sentence_index)
        )
        texts: dict[uuid.UUID, list[str]] = {}
        for paragraph_id, text in rows.all():
            texts.setdefault(paragraph_id, []).append(text)

        planned = []
        for paragraph_id in paragraph_ids:
            sentences = texts.get(paragraph_id)
            if paragraph_id not in books or not sentences:
                continue
            keys = [
                sentence_cache_key(self._tts.info, self._request(t, voice), self._tts.sample_rate)
                for t in sentences
            ]
            planned.append(
                PlannedParagraph(
                    paragraph_id=paragraph_id,
                    book_id=books[paragraph_id],
                    sentence_texts=sentences,
                    sentence_keys=keys,
                    cache_key=paragraph_cache_key(keys, audio_format=self._format),
                )
            )
        return planned

    async def lookup(
        self, paragraph_ids: Sequence[uuid.UUID], voice: Voice
    ) -> dict[uuid.UUID, tuple[PlannedParagraph, AudioAsset | None]]:
        async with self._sessionmaker() as session:
            planned = await self.plan(session, paragraph_ids, voice)
            keys = [p.cache_key for p in planned]
            assets = {
                a.cache_key: a
                for a in (
                    await session.execute(select(AudioAsset).where(AudioAsset.cache_key.in_(keys)))
                ).scalars()
            }
            if assets:
                await session.execute(
                    update(AudioAsset)
                    .where(AudioAsset.cache_key.in_(list(assets)))
                    .values(last_accessed_at=utcnow())
                )
                await session.commit()
        return {p.paragraph_id: (p, assets.get(p.cache_key)) for p in planned}

    # ------------------------------------------------------------------ rendering

    async def render(self, paragraph_id: uuid.UUID, voice: Voice) -> AudioAsset:
        if self._encoder is None:
            raise RuntimeError("lookup-only renderer cannot render")
        encoder = self._encoder
        found = await self.lookup([paragraph_id], voice)
        if paragraph_id not in found:
            raise AudioUnavailable(str(paragraph_id))
        planned, existing = found[paragraph_id]
        if existing is not None:
            return existing

        clips: list[PcmAudio] = []
        billed = 0
        for text, key in zip(planned.sentence_texts, planned.sentence_keys, strict=True):
            clip, characters = await self._sentence_clip(planned, text, key, voice)
            clips.append(clip)
            billed += characters

        sample_rate = clips[0].sample_rate
        if any(c.sample_rate != sample_rate for c in clips):
            raise RuntimeError("sentence clips have different sample rates")
        timings: list[dict[str, Any]] = []
        position_ms = 0
        joined = bytearray()
        for index, clip in enumerate(clips):
            joined += clip.samples
            end_ms = round(len(joined) // 2 * 1000 / sample_rate)
            timings.append({"sentence_index": index, "start_ms": position_ms, "end_ms": end_ms})
            position_ms = end_ms
        paragraph_pcm = PcmAudio(bytes(joined), sample_rate)
        encoded = await encoder.encode(paragraph_pcm)
        storage_key = paragraph_storage_key(planned.cache_key, encoded.extension)
        await self._storage.put_bytes(storage_key, encoded.data, content_type=encoded.content_type)

        async with self._sessionmaker() as session:
            await _insert_ignore(
                session,
                {
                    "id": uuid.uuid4(),
                    "cache_key": planned.cache_key,
                    "kind": AudioKind.PARAGRAPH,
                    "book_id": planned.book_id,
                    "paragraph_id": planned.paragraph_id,
                    "text_hash": text_hash(" ".join(planned.sentence_texts)),
                    "voice_key": voice.key,
                    "provider": self._tts.info.provider,
                    "model_version": self._tts.info.model,
                    "format": self._format,
                    "sample_rate": sample_rate,
                    "duration_ms": paragraph_pcm.duration_ms,
                    "byte_size": len(encoded.data),
                    "storage_key": storage_key,
                    "timings": timings,
                    # Billing belongs to the sentence rows (one provider call each). A paragraph is a
                    # concatenation, so charging it too would double-count SUM(characters_billed).
                    "characters_billed": 0,
                },
            )
            await session.commit()
            asset = (
                await session.execute(select(AudioAsset).where(AudioAsset.cache_key == planned.cache_key))
            ).scalar_one()
        logger.info(
            "paragraph_audio_rendered",
            extra={"paragraph_id": str(paragraph_id), "sentences": len(clips), "characters_billed": billed},
        )
        return asset

    async def _sentence_clip(
        self, planned: PlannedParagraph, text: str, key: str, voice: Voice
    ) -> tuple[PcmAudio, int]:
        async with self._sessionmaker() as session:
            cached = (
                await session.execute(select(AudioAsset).where(AudioAsset.cache_key == key))
            ).scalar_one_or_none()
        if cached is not None:
            try:
                return from_wav(await self._storage.get_bytes(cached.storage_key)), 0
            except ObjectNotFound:
                logger.warning("sentence_audio_missing_in_storage", extra={"asset_id": str(cached.id)})

        result = await self._tts.synthesize(self._request(text, voice))
        storage_key = sentence_storage_key(key)
        await self._storage.put_bytes(storage_key, to_wav(result.audio), content_type="audio/wav")
        async with self._sessionmaker() as session:
            await _insert_ignore(
                session,
                {
                    "id": uuid.uuid4(),
                    "cache_key": key,
                    "kind": AudioKind.SENTENCE,
                    "book_id": planned.book_id,
                    "paragraph_id": planned.paragraph_id,
                    "text_hash": text_hash(text),
                    "voice_key": voice.key,
                    "provider": self._tts.info.provider,
                    "model_version": self._tts.info.model,
                    "format": "wav",
                    "sample_rate": result.audio.sample_rate,
                    "duration_ms": result.audio.duration_ms,
                    "byte_size": len(result.audio.samples) + 44,
                    "storage_key": storage_key,
                    "timings": None,
                    "characters_billed": result.characters_billed,
                },
            )
            await session.commit()
        return result.audio, result.characters_billed


async def _insert_ignore(session: AsyncSession, values: dict[str, Any]) -> None:
    dialect = session.get_bind().dialect.name
    table = cast(Table, AudioAsset.__table__)
    if dialect == "postgresql":
        statement: Any = (
            postgresql.insert(table).values(**values).on_conflict_do_nothing(index_elements=["cache_key"])
        )
    elif dialect == "sqlite":
        statement = sqlite.insert(table).values(**values).on_conflict_do_nothing(index_elements=["cache_key"])
    else:  # pragma: no cover
        raise RuntimeError(f"unsupported dialect {dialect}")
    await session.execute(statement)
