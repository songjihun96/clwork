"""retrieval chunks (pgvector) and question/answer history

Revision ID: 0004_rag
Revises: 0003_audio_assets
Create Date: 2026-09-16

The vector column is ``vector(1024)`` on PostgreSQL and a JSON array on SQLite, matching
story_core.db.types.embedding_column: local tests exercise the same rows and the same spoiler filter with
an exact-scan searcher, while production uses the HNSW index.

Three indexes carry PostgreSQL-only options, which SQLite ignores (it builds a plain index instead —
unused there, but the migration and the ORM metadata then match on both dialects):
* HNSW with ``vector_cosine_ops`` for nearest-neighbour search;
* GIN trigram on the chunk text, which is what makes the keyword path's ``LIKE '%term%'`` indexable
  (PostgreSQL has no Korean morphological analyser — see docs/database.md §3.3);
* GIN trigram on ``sentences.text`` for the spoiler guard's first-occurrence lookup.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_rag"
down_revision: str | None = "0003_audio_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
# Keep in sync with story_core.models.rag.EMBEDDING_DIMENSIONS. A different width is a new table.
EMBEDDING_DIMENSIONS = 1024
_HNSW_OPTIONS = {"m": 16, "ef_construction": 64}


def upgrade() -> None:
    op.create_table(
        "paragraph_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("paragraph_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_global_seq", sa.Integer(), nullable=False),
        sa.Column("end_global_seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIMENSIONS).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name=op.f("fk_paragraph_embeddings_book_id_books"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paragraph_embeddings")),
        sa.UniqueConstraint("book_id", "model_id", "chunk_index", name="uq_paragraph_embeddings_book_chunk"),
    )
    op.create_index(op.f("ix_paragraph_embeddings_book_id"), "paragraph_embeddings", ["book_id"])
    op.create_index(
        "ix_paragraph_embeddings_book_end_seq", "paragraph_embeddings", ["book_id", "end_global_seq"]
    )
    op.create_index("ix_paragraph_embeddings_content", "paragraph_embeddings", ["model_id", "content_hash"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_active_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["reading_sessions.id"],
            name=op.f("fk_conversations_session_id_reading_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_conversations_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(op.f("ix_conversations_session_id"), "conversations", ["session_id"])
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("position_global_seq", sa.Integer(), nullable=True),
        sa.Column("retrieval_refs", _JSON, nullable=True),
        sa.Column("latency_ms", _JSON, nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("guard_action", sa.String(length=16), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        "ix_messages_conversation_created", "conversation_messages", ["conversation_id", "created_at"]
    )

    op.create_index(
        "ix_paragraph_embeddings_hnsw",
        "paragraph_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=_HNSW_OPTIONS,
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_paragraph_embeddings_text_trgm",
        "paragraph_embeddings",
        ["text"],
        postgresql_using="gin",
        postgresql_ops={"text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_sentences_text_trgm",
        "sentences",
        ["text"],
        postgresql_using="gin",
        postgresql_ops={"text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_sentences_text_trgm", table_name="sentences")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("paragraph_embeddings")
