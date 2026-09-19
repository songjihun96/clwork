"""The Alembic migration chain must produce exactly the schema the ORM models describe."""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from story_core.models import Base

API_ROOT = Path(__file__).resolve().parents[1]


def _config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


@pytest.mark.skipif(bool(os.environ.get("TEST_DATABASE_URL")), reason="SQLite migration check")
def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path: Path) -> None:
    db_file = tmp_path / "migrations.db"
    config = _config(f"sqlite+aiosqlite:///{db_file}")

    command.upgrade(config, "head")

    sync_engine = create_engine(f"sqlite:///{db_file}")
    with sync_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"

    command.downgrade(config, "base")
    with sync_engine.connect() as connection:
        remaining = set(inspect(connection).get_table_names()) - {"alembic_version"}
    sync_engine.dispose()
    assert remaining == set()


def _inspect(connection: Connection) -> tuple[list[object], set[str]]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    diff = compare_metadata(context, Base.metadata)
    return diff, set(inspect(connection).get_table_names()) - {"alembic_version"}


@pytest.mark.skipif(
    not (os.environ.get("TEST_DATABASE_URL") or "").startswith("postgresql"),
    reason="PostgreSQL migration check needs TEST_DATABASE_URL",
)
async def test_postgresql_upgrade_matches_models_and_downgrade_is_clean() -> None:
    """The same check on PostgreSQL: JSONB, enums and timestamptz never reach SQLite."""
    base_url = make_url(os.environ["TEST_DATABASE_URL"])
    database = f"{base_url.database}_migrations"
    admin = create_async_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'drop database if exists "{database}"')
            await connection.exec_driver_sql(f'create database "{database}"')
    finally:
        await admin.dispose()

    url = base_url.set(database=database)
    engine = create_async_engine(url)
    try:
        await asyncio.to_thread(command.upgrade, _config(url.render_as_string(hide_password=False)), "head")
        async with engine.connect() as connection:
            diff, tables = await connection.run_sync(_inspect)
        assert diff == [], f"models and migrations differ on PostgreSQL: {diff}"
        assert "audio_assets" in tables, "migration 0003 did not run"

        await asyncio.to_thread(command.downgrade, _config(url.render_as_string(hide_password=False)), "base")
        async with engine.connect() as connection:
            _, remaining = await connection.run_sync(_inspect)
        assert remaining == set(), f"downgrade left tables behind: {remaining}"
    finally:
        await engine.dispose()
        admin = create_async_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'drop database if exists "{database}"')
        await admin.dispose()
