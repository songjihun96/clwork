"""Cached narration audio. See docs/database.md §3.7 and docs/provider-abstraction.md §6.

Rows are addressed by ``cache_key`` (content + provider + model + voice + parameters), never by
paragraph id alone: reprocessing a book with unchanged text reuses audio, and a model or voice change
can never replay stale audio. ``paragraph_id``/``book_id`` are lookup columns without foreign keys,
because content rows are replaced on reprocessing while the cached audio stays valid.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from story_core.db.types import JSONDocument, UTCDateTime
from story_core.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from story_core.time import utcnow


class AudioKind(StrEnum):
    SENTENCE = "sentence"  # internal building block (PCM WAV), never served to clients
    PARAGRAPH = "paragraph"  # delivery file with sentence timings


class AudioAsset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audio_assets"

    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    book_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    paragraph_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    voice_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Set for personal voices (Phase 10) so voice deletion can find and delete derived audio.
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # [{"sentence_index": 0, "start_ms": 0, "end_ms": 1234}, ...] for paragraph assets.
    timings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONDocument)
    characters_billed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
