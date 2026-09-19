"""Retrieval chunks and question/answer history. See docs/database.md §3.3 and §3.6.

The embedding width is pinned by ``EMBEDDING_DIMENSIONS``: one column never mixes two models' widths.
Swapping to a model with a different width is a migration that creates a second table, backfills it and
switches over — not an in-place column change, which would silently mix vector spaces mid-book.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from story_core.db.types import JSONDocument, UTCDateTime, embedding_column
from story_core.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

# bge-m3 class models; must equal EmbeddingProvider.dimensions (checked at start-up).
EMBEDDING_DIMENSIONS = 1024


class ParagraphEmbedding(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "paragraph_embeddings"
    __table_args__ = (
        UniqueConstraint("book_id", "model_id", "chunk_index", name="uq_paragraph_embeddings_book_chunk"),
        # The spoiler filter reads this on every question: (book, end_global_seq) covers it exactly.
        Index("ix_paragraph_embeddings_book_end_seq", "book_id", "end_global_seq"),
        Index("ix_paragraph_embeddings_content", "model_id", "content_hash"),
        # Nearest-neighbour search. Declared here so the ORM describes the production schema; the
        # dialect options are ignored on SQLite, where search is an exact scan anyway.
        Index(
            "ix_paragraph_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Makes the keyword path's LIKE '%term%' indexable (no Korean analyser in PostgreSQL).
        Index(
            "ix_paragraph_embeddings_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # No FK: reprocessing replaces paragraph rows, and identical text must stay reusable without paying
    # the provider again (same reasoning as audio_assets).
    paragraph_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_global_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # Highest sentence number in the chunk: the only thing the spoiler filter compares against.
    end_global_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(embedding_column(EMBEDDING_DIMENSIONS), nullable=False)


class Conversation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "conversations"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ConversationMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32))
    # Reading position when the turn happened: evaluation and spoiler audits need it, and it is what
    # "answer from where the reader is" means when the history is replayed.
    position_global_seq: Mapped[int | None] = mapped_column(Integer)
    # Chunk ids that grounded the answer, for evaluation and for auditing a spoiler complaint.
    retrieval_refs: Mapped[list[Any] | None] = mapped_column(JSONDocument)
    latency_ms: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    # True when the spoiler guard rewrote or replaced the model's answer.
    guard_action: Mapped[str | None] = mapped_column(String(16))
