"""Reading sessions and positions. See docs/database.md §3.5."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from story_core.db.types import UTCDateTime
from story_core.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from story_core.reading.state_machine import ReadingState
from story_core.time import utcnow


class SpoilerMode(StrEnum):
    NO_SPOILER = "NO_SPOILER"
    LIGHT_SPOILER = "LIGHT_SPOILER"
    FULL_SPOILER = "FULL_SPOILER"


class ReadingSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reading_sessions"
    __table_args__ = (
        # One active session per user and book.
        Index(
            "uq_reading_sessions_active_user_book",
            "user_id",
            "book_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # FK added with voice_profiles in Phase 10.
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column()
    spoiler_mode: Mapped[str] = mapped_column(String(16), default=SpoilerMode.NO_SPOILER, nullable=False)
    playback_state: Mapped[str] = mapped_column(String(24), default=ReadingState.IDLE, nullable=False)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Furthest sentence ever reached: re-reading earlier pages must not narrow the spoiler window.
    max_read_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReadingPosition(Base):
    __tablename__ = "reading_positions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    # SET NULL: reprocessing a book replaces content rows; the position is re-attached by global_seq.
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    paragraph_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("paragraphs.id", ondelete="SET NULL"))
    sentence_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sentence_global_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
