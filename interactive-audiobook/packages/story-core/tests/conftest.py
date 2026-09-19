import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from story_core.books.rights import RightsType
from story_core.db.extensions import ensure_extensions
from story_core.db.session import DatabaseOptions, create_engine, create_sessionmaker
from story_core.models import Base, Book, BookRights, BookStatus, User
from story_core.storage.local import LocalFileStorage

TODAY = date(2026, 9, 15)


@dataclass
class Db:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Db]:
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'core.db'}"
    engine = create_engine(DatabaseOptions(url=url, application_name="story-core-tests"))
    async with engine.begin() as conn:
        # create_all skips migrations, so the extensions they install must be ensured here.
        await ensure_extensions(conn)
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield Db(engine, create_sessionmaker(engine))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "storage")


async def create_user(db: Db, email: str | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with db.sessionmaker() as session:
        session.add(User(id=user_id, email=email or f"{user_id.hex[:8]}@example.com"))
        await session.commit()
    return user_id


async def create_book(
    db: Db,
    storage: LocalFileStorage,
    source: bytes,
    *,
    source_format: str = "txt",
    status: BookStatus = BookStatus.QUEUED,
    rights_type: RightsType = RightsType.OWNED,
    commercial_use: bool = True,
    audio_rights: bool = True,
    ai_processing_rights: bool = True,
    rights_holder: str | None = "Test Publisher",
    license_start: date | None = None,
    license_end: date | None = None,
) -> uuid.UUID:
    book_id = uuid.uuid4()
    digest = hashlib.sha256(source).hexdigest()
    key = f"books/{book_id}/source/{digest}.{source_format}"
    await storage.put_bytes(key, source, content_type="application/octet-stream")
    async with db.sessionmaker() as session:
        session.add(
            Book(
                id=book_id,
                title="등대지기의 밤",
                source_format=source_format,
                source_storage_key=key,
                source_sha256=digest,
                source_byte_size=len(source),
                status=status,
            )
        )
        await session.flush()
        session.add(
            BookRights(
                book_id=book_id,
                rights_type=rights_type,
                rights_holder=rights_holder,
                commercial_use=commercial_use,
                audio_rights=audio_rights,
                ai_processing_rights=ai_processing_rights,
                license_start=license_start,
                license_end=license_end,
            )
        )
        await session.commit()
    return book_id


SAMPLE_TEXT = (
    "제1장 바람이 바뀌던 날\n\n"
    "섬의 끝에는 오래된 등대가 하나 서 있었다. 하얀 벽은 소금기에 바래 있었다. 계단은 낮은 소리를 냈다.\n\n"
    "그날은 바람의 냄새가 달랐다. 하람은 수평선을 오래 바라보았다.\n\n"
    "***\n\n"
    "멀리서 작은 불빛 하나가 깜박였다.\n\n"
    "제2장 낮게 뜬 불빛\n\n"
    "하람은 손전등을 챙겨 바위길로 내려갔다. 파도가 발목까지 올라왔다.\n\n"
    '"누구 있어요? 대답해 주세요!" 하람이 외쳤다. 아무 대답도 없었다.\n'
).encode()
