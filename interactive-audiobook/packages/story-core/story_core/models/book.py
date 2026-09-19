"""Book content tables. See docs/database.md §3.2.

Ordering never relies on primary keys: ``sequence`` orders within a parent and ``global_seq`` orders
across the whole book (spoiler filter, progress, resume). Content rows are replaced as a whole when a
book is reprocessed; reading positions survive through ``sentence_global_seq``.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from story_core.db.types import UTCDateTime
from story_core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BookStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SourceFormat(StrEnum):
    EPUB = "epub"
    TXT = "txt"


class Book(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(16), default="ko", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=BookStatus.UPLOADED, index=True, nullable=False)
    source_format: Mapped[str] = mapped_column(String(8), nullable=False)
    source_storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processing_error: Mapped[str | None] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    total_paragraphs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sentences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class BookRights(TimestampMixin, Base):
    __tablename__ = "book_rights"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    rights_type: Mapped[str] = mapped_column(String(24), nullable=False)
    rights_holder: Mapped[str | None] = mapped_column(String(200))
    license_start: Mapped[date | None] = mapped_column(Date)
    license_end: Mapped[date | None] = mapped_column(Date)
    commercial_use: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audio_rights: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_processing_rights: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    territory: Mapped[str | None] = mapped_column(String(64))
    contract_ref: Mapped[str | None] = mapped_column(String(128))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Chapter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "sequence", name="uq_chapters_book_id_sequence"),)

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    first_sentence_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)


class Section(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("chapter_id", "sequence", name="uq_sections_chapter_id_sequence"),)

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))


class Paragraph(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "paragraphs"
    __table_args__ = (
        UniqueConstraint("book_id", "global_seq", name="uq_paragraphs_book_id_global_seq"),
        UniqueConstraint("chapter_id", "sequence", name="uq_paragraphs_chapter_id_sequence"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    global_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_sentence_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_break_before: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Filled by the Scene Engine (Phase 8); no FK until the scenes table exists.
    scene_id: Mapped[uuid.UUID | None] = mapped_column()


class Sentence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sentences"
    __table_args__ = (
        UniqueConstraint("book_id", "global_seq", name="uq_sentences_book_id_global_seq"),
        UniqueConstraint("paragraph_id", "sentence_index", name="uq_sentences_paragraph_id_sentence_index"),
        # The spoiler guard asks "where does this term first appear?" with LIKE '%term%'; a trigram index
        # is what keeps that off a full scan (PostgreSQL has no Korean morphological analyser).
        Index(
            "ix_sentences_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    paragraph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=False
    )
    sentence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    global_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
