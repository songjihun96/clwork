"""audio assets (cached narration)

Revision ID: 0003_audio_assets
Revises: 0002_books_reading
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_audio_assets"
down_revision: str | None = "0002_books_reading"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "audio_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("paragraph_id", sa.Uuid(), nullable=True),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("voice_key", sa.String(length=128), nullable=False),
        sa.Column("voice_profile_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("timings", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("characters_billed", sa.Integer(), nullable=False),
        sa.Column("last_accessed_at", _TS, nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audio_assets")),
        sa.UniqueConstraint("cache_key", name=op.f("uq_audio_assets_cache_key")),
    )
    op.create_index(op.f("ix_audio_assets_book_id"), "audio_assets", ["book_id"])
    op.create_index(op.f("ix_audio_assets_paragraph_id"), "audio_assets", ["paragraph_id"])
    op.create_index(op.f("ix_audio_assets_voice_profile_id"), "audio_assets", ["voice_profile_id"])


def downgrade() -> None:
    op.drop_table("audio_assets")
