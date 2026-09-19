"""Load the project's original sample text as a readable book (development only).

    python scripts/seed_sample_book.py

Runs ingestion inline, so no worker or Redis is needed. The sample text was written for this project,
so the rights record is "owned" with every right granted.
"""

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from story_core.db.session import create_engine, create_sessionmaker
from story_core.ingestion.pipeline import ingest_book
from story_core.models import Book, BookRights, BookStatus, SourceFormat
from story_core.storage.local import LocalFileStorage

from app.config import Environment, Settings

SAMPLE_NAME = "lighthouse-sample.txt"
# Repository checkout and container image put the seed text in different places.
SAMPLE_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "seed" / SAMPLE_NAME,  # container image (services/api/seed)
    *[
        parent / "infrastructure" / "seed" / SAMPLE_NAME
        for parent in Path(__file__).resolve().parents
    ],
]
TITLE = "등대지기의 밤"


async def main() -> int:
    settings = Settings()
    if settings.env is Environment.PRODUCTION:
        print("refusing to seed sample content in production", file=sys.stderr)
        return 1
    sample = next((path for path in SAMPLE_CANDIDATES if path.is_file()), None)
    if sample is None:
        print(f"sample text {SAMPLE_NAME} not found", file=sys.stderr)
        return 1
    data = sample.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    engine = create_engine(settings.database_options)
    sessionmaker = create_sessionmaker(engine)
    storage = LocalFileStorage(settings.storage_local_root)
    try:
        async with sessionmaker() as session:
            existing = await session.scalar(select(Book.id).where(Book.source_sha256 == digest))
            if existing is not None:
                print(f"already seeded: {existing}")
                return 0
            book_id = uuid.uuid4()
            key = f"books/{book_id}/source/{digest}.txt"
            await storage.put_bytes(key, data, content_type="text/plain")
            session.add(
                Book(
                    id=book_id,
                    title=TITLE,
                    author="Interactive Audiobook 샘플",
                    description="개발·테스트용으로 이 프로젝트에서 직접 작성한 짧은 이야기입니다.",
                    status=BookStatus.QUEUED,
                    source_format=SourceFormat.TXT,
                    source_storage_key=key,
                    source_sha256=digest,
                    source_byte_size=len(data),
                )
            )
            await session.flush()
            session.add(
                BookRights(
                    book_id=book_id,
                    rights_type="owned",
                    rights_holder="Interactive Audiobook project",
                    commercial_use=True,
                    audio_rights=True,
                    ai_processing_rights=True,
                    contract_ref="original-sample-text",
                )
            )
            await session.commit()
        outcome = await ingest_book(sessionmaker, storage, book_id)
        print(f"{book_id}: {outcome.status} ({outcome.paragraphs} paragraphs, {outcome.sentences} sentences)")
        return 0 if outcome.status == BookStatus.READY else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
