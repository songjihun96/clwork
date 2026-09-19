from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True, slots=True)
class DatabaseOptions:
    url: str
    application_name: str
    pool_size: int = 10
    connect_timeout_s: float = 5.0
    statement_timeout_ms: int = 5000


def create_engine(options: DatabaseOptions) -> AsyncEngine:
    url = make_url(options.url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    backend = url.get_backend_name()

    if backend == "postgresql":
        kwargs.update(
            pool_size=options.pool_size,
            max_overflow=max(2, options.pool_size // 2),
            pool_timeout=options.connect_timeout_s,
            connect_args={
                "timeout": options.connect_timeout_s,
                "server_settings": {
                    "statement_timeout": str(options.statement_timeout_ms),
                    "application_name": options.application_name,
                },
            },
        )

    engine = create_async_engine(url, **kwargs)

    if backend == "sqlite":
        # SQLite ignores foreign keys (and ON DELETE CASCADE) unless enabled per connection.
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
