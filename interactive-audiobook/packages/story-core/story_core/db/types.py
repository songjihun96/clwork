from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class UTCDateTime(TypeDecorator[datetime]):
    """timestamptz that always round-trips as a timezone-aware UTC datetime.

    PostgreSQL returns aware values already; SQLite (used in fast local tests) returns
    naive ones, which would break comparisons with ``utcnow()``.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed; use timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# JSONB on PostgreSQL, plain JSON elsewhere.
JSONDocument = JSON().with_variant(JSONB(), "postgresql")


def embedding_column(dimensions: int) -> TypeEngine[list[float]]:
    """``vector(N)`` on PostgreSQL, a JSON array on SQLite.

    Production search runs in PostgreSQL with an HNSW index. SQLite keeps the fast local suite able to
    exercise the *same* rows and the same spoiler filter with an exact-scan searcher, so the safety-
    critical query is covered without a database service (see story_core.rag.search).
    """
    return Vector(dimensions).with_variant(JSON(), "sqlite")
