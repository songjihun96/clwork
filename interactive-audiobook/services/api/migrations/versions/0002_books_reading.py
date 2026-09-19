"""books, book rights, content hierarchy, reading sessions and positions; user roles

Revision ID: 0002_books_reading
Revises: 0001_accounts
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_books_reading"
down_revision: str | None = "0001_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(length=16), server_default="reader", nullable=False))

    op.create_table(
        "books",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_format", sa.String(length=8), nullable=False),
        sa.Column("source_storage_key", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_byte_size", sa.Integer(), nullable=False),
        sa.Column("processing_version", sa.Integer(), nullable=False),
        sa.Column("processing_error", sa.String(length=64), nullable=True),
        sa.Column("processed_at", _TS, nullable=True),
        sa.Column("total_paragraphs", sa.Integer(), nullable=False),
        sa.Column("total_sentences", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_books_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_books")),
    )
    op.create_index(op.f("ix_books_status"), "books", ["status"])

    op.create_table(
        "book_rights",
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("rights_type", sa.String(length=24), nullable=False),
        sa.Column("rights_holder", sa.String(length=200), nullable=True),
        sa.Column("license_start", sa.Date(), nullable=True),
        sa.Column("license_end", sa.Date(), nullable=True),
        sa.Column("commercial_use", sa.Boolean(), nullable=False),
        sa.Column("audio_rights", sa.Boolean(), nullable=False),
        sa.Column("ai_processing_rights", sa.Boolean(), nullable=False),
        sa.Column("territory", sa.String(length=64), nullable=True),
        sa.Column("contract_ref", sa.String(length=128), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_book_rights_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"], ["users.id"], name=op.f("fk_book_rights_verified_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("book_id", name=op.f("pk_book_rights")),
    )

    op.create_table(
        "chapters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("first_sentence_seq", sa.Integer(), nullable=False),
        sa.Column("sentence_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_chapters_book_id_books"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chapters")),
        sa.UniqueConstraint("book_id", "sequence", name="uq_chapters_book_id_sequence"),
    )
    op.create_index(op.f("ix_chapters_book_id"), "chapters", ["book_id"])

    op.create_table(
        "sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_sections_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"], ["chapters.id"], name=op.f("fk_sections_chapter_id_chapters"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sections")),
        sa.UniqueConstraint("chapter_id", "sequence", name="uq_sections_chapter_id_sequence"),
    )
    op.create_index(op.f("ix_sections_book_id"), "sections", ["book_id"])

    op.create_table(
        "paragraphs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("global_seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("first_sentence_seq", sa.Integer(), nullable=False),
        sa.Column("sentence_count", sa.Integer(), nullable=False),
        sa.Column("scene_break_before", sa.Boolean(), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_paragraphs_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_paragraphs_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_paragraphs_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paragraphs")),
        sa.UniqueConstraint("book_id", "global_seq", name="uq_paragraphs_book_id_global_seq"),
        sa.UniqueConstraint("chapter_id", "sequence", name="uq_paragraphs_chapter_id_sequence"),
    )
    op.create_index(op.f("ix_paragraphs_section_id"), "paragraphs", ["section_id"])

    op.create_table(
        "sentences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("paragraph_id", sa.Uuid(), nullable=False),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("global_seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_sentences_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["paragraph_id"],
            ["paragraphs.id"],
            name=op.f("fk_sentences_paragraph_id_paragraphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sentences")),
        sa.UniqueConstraint("book_id", "global_seq", name="uq_sentences_book_id_global_seq"),
        sa.UniqueConstraint(
            "paragraph_id", "sentence_index", name="uq_sentences_paragraph_id_sentence_index"
        ),
    )

    op.create_table(
        "reading_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("voice_profile_id", sa.Uuid(), nullable=True),
        sa.Column("spoiler_mode", sa.String(length=16), nullable=False),
        sa.Column("playback_state", sa.String(length=24), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("max_read_seq", sa.Integer(), nullable=False),
        sa.Column("last_active_at", _TS, nullable=False),
        sa.Column("ended_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_reading_sessions_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_reading_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reading_sessions")),
    )
    op.create_index(op.f("ix_reading_sessions_user_id"), "reading_sessions", ["user_id"])
    op.create_index(op.f("ix_reading_sessions_book_id"), "reading_sessions", ["book_id"])
    op.create_index(
        "uq_reading_sessions_active_user_book",
        "reading_sessions",
        ["user_id", "book_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "reading_positions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=True),
        sa.Column("paragraph_id", sa.Uuid(), nullable=True),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("sentence_global_seq", sa.Integer(), nullable=False),
        sa.Column("position_version", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_reading_positions_chapter_id_chapters"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paragraph_id"],
            ["paragraphs.id"],
            name=op.f("fk_reading_positions_paragraph_id_paragraphs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["reading_sessions.id"],
            name=op.f("fk_reading_positions_session_id_reading_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_reading_positions")),
    )


def downgrade() -> None:
    op.drop_table("reading_positions")
    op.drop_index("uq_reading_sessions_active_user_book", table_name="reading_sessions")
    op.drop_table("reading_sessions")
    op.drop_table("sentences")
    op.drop_table("paragraphs")
    op.drop_table("sections")
    op.drop_table("chapters")
    op.drop_table("book_rights")
    op.drop_table("books")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")
