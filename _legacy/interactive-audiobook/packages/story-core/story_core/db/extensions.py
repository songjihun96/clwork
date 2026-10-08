"""PostgreSQL extensions the schema depends on.

Production gets these from the first Alembic revision. Tests build their schema with
``metadata.create_all``, which skips migrations entirely, so they need the same extensions installed or
the trigram and vector indexes cannot be created — a fresh ``CREATE DATABASE`` has neither.
"""

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import text

REQUIRED_EXTENSIONS = ("vector", "pg_trgm")


async def ensure_extensions(connection: AsyncConnection) -> None:
    """No-op on SQLite. Raises with an actionable message if the role may not install them."""
    if connection.dialect.name != "postgresql":
        return
    for extension in REQUIRED_EXTENSIONS:
        try:
            await connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        except ProgrammingError as exc:  # insufficient_privilege
            raise RuntimeError(
                f"the '{extension}' extension is missing and this role may not create it; "
                f"run 'CREATE EXTENSION {extension}' as a superuser on this database"
            ) from exc
