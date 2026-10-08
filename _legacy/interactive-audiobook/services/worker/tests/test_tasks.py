"""API enqueues by task *name*; the worker must run it (checked with the in-memory broker)."""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from story_core.db.session import DatabaseOptions, create_engine, create_sessionmaker
from story_core.jobs.queue import INGEST_BOOK_TASK, TaskiqJobQueue
from story_core.models import (
    EMBEDDING_DIMENSIONS,
    Base,
    Book,
    BookRights,
    BookStatus,
    ParagraphEmbedding,
    Sentence,
)
from story_core.providers.embedding.fake import FakeEmbeddingProvider
from story_core.rag.index import ChunkIndexer
from story_core.storage.local import LocalFileStorage
from taskiq import InMemoryBroker

from worker.tasks import WorkerResources, register_tasks

TEXT = "제1장 시작\n\n등대가 있었다. 불빛이 깜박였다.\n".encode()


async def test_enqueued_ingest_job_runs_in_worker_and_chains_embedding(tmp_path: Path) -> None:
    """Ingestion and embedding are separate jobs; a finished ingest kicks the embed job itself."""
    engine = create_engine(
        DatabaseOptions(url=f"sqlite+aiosqlite:///{tmp_path / 'w.db'}", application_name="t")
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = create_sessionmaker(engine)
    storage = LocalFileStorage(tmp_path / "storage")

    book_id = uuid.uuid4()
    key = f"books/{book_id}/source/{hashlib.sha256(TEXT).hexdigest()}.txt"
    await storage.put_bytes(key, TEXT, content_type="text/plain")
    async with sessionmaker() as session:
        session.add(
            Book(
                id=book_id,
                title="t",
                source_format="txt",
                source_storage_key=key,
                source_sha256="0" * 64,
                source_byte_size=len(TEXT),
                status=BookStatus.QUEUED,
            )
        )
        await session.flush()
        session.add(
            BookRights(
                book_id=book_id,
                rights_type="public_domain",
                commercial_use=True,
                audio_rights=True,
                ai_processing_rights=True,
            )
        )
        await session.commit()

    embedder = FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    broker = InMemoryBroker()
    register_tasks(
        broker,
        lambda: WorkerResources(sessionmaker, storage, chunk_indexer=ChunkIndexer(sessionmaker, embedder)),
    )
    await broker.startup()
    try:
        # Exactly what services/api does: kick by name, without importing worker code.
        await TaskiqJobQueue(broker).enqueue(INGEST_BOOK_TASK, book_id=str(book_id), expected_version=0)
        await broker.wait_all()
        # The ingest task kicked books.embed while it ran; wait for that one too.
        await broker.wait_all()
    finally:
        await broker.shutdown()

    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        sentences = (
            (await session.execute(select(Sentence.text).order_by(Sentence.global_seq))).scalars().all()
        )
        chunks = (await session.execute(select(ParagraphEmbedding))).scalars().all()
    await engine.dispose()

    assert book is not None and book.status == BookStatus.READY
    assert sentences == ["등대가 있었다.", "불빛이 깜박였다."]
    assert chunks and all(len(chunk.embedding) == EMBEDDING_DIMENSIONS for chunk in chunks)
    assert all(chunk.model_id == embedder.info.model for chunk in chunks)


async def test_enqueued_audio_job_renders_paragraph(tmp_path: Path) -> None:
    from story_core.audio.encoding import WavEncoder
    from story_core.audio.renderer import ParagraphAudioRenderer
    from story_core.ingestion.pipeline import ingest_book
    from story_core.jobs.queue import RENDER_PARAGRAPH_AUDIO_TASK
    from story_core.models import AudioAsset, AudioKind, Paragraph
    from story_core.providers.tts.fake import FakeTTSProvider

    engine = create_engine(
        DatabaseOptions(url=f"sqlite+aiosqlite:///{tmp_path / 'a.db'}", application_name="t")
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = create_sessionmaker(engine)
    storage = LocalFileStorage(tmp_path / "storage")
    book_id = uuid.uuid4()
    key = f"books/{book_id}/source/x.txt"
    await storage.put_bytes(key, TEXT, content_type="text/plain")
    async with sessionmaker() as session:
        session.add(
            Book(
                id=book_id,
                title="t",
                source_format="txt",
                source_storage_key=key,
                source_sha256="0" * 64,
                source_byte_size=len(TEXT),
                status=BookStatus.QUEUED,
            )
        )
        await session.flush()
        session.add(
            BookRights(
                book_id=book_id,
                rights_type="public_domain",
                commercial_use=True,
                audio_rights=True,
                ai_processing_rights=True,
            )
        )
        await session.commit()
    await ingest_book(sessionmaker, storage, book_id)
    async with sessionmaker() as session:
        paragraph_id = (await session.execute(select(Paragraph.id))).scalar_one()

    tts = FakeTTSProvider()
    broker = InMemoryBroker()
    register_tasks(
        broker,
        lambda: WorkerResources(
            sessionmaker,
            storage,
            audio_renderer=ParagraphAudioRenderer(sessionmaker, storage, tts, WavEncoder()),
        ),
    )
    await broker.startup()
    try:
        queue = TaskiqJobQueue(broker)
        for _ in range(2):  # duplicate delivery must not synthesise twice
            await queue.enqueue(
                RENDER_PARAGRAPH_AUDIO_TASK,
                paragraph_id=str(paragraph_id),
                voice_id="fake-narrator",
                voice_version="1",
            )
            await broker.wait_all()
    finally:
        await broker.shutdown()

    async with sessionmaker() as session:
        kinds = (await session.execute(select(AudioAsset.kind))).scalars().all()
    await engine.dispose()
    assert sorted(kinds) == [AudioKind.PARAGRAPH, AudioKind.SENTENCE, AudioKind.SENTENCE]
    assert len(tts.calls) == 2
