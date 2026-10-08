import uuid

from sqlalchemy import func, select

from story_core.ingestion.pipeline import ingest_book
from story_core.models import Book, BookStatus, Chapter, Paragraph, ReadingPosition, Section, Sentence
from story_core.reading.sessions import ReadingSessionService
from tests.conftest import SAMPLE_TEXT, TODAY, Db, create_book, create_user
from tests.epub_factory import SAMPLE_EPUB_DOCS, build_epub


async def test_ingest_text_book_builds_ordered_content(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, SAMPLE_TEXT)
    outcome = await ingest_book(db.sessionmaker, storage, book_id, expected_version=0, today=lambda: TODAY)
    assert outcome.status == "ready" and outcome.error is None

    async with db.sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book is not None
        assert book.status == BookStatus.READY and book.processing_version == 1
        chapters = (await session.execute(select(Chapter).order_by(Chapter.sequence))).scalars().all()
        paragraphs = (await session.execute(select(Paragraph).order_by(Paragraph.global_seq))).scalars().all()
        sentences = (await session.execute(select(Sentence).order_by(Sentence.global_seq))).scalars().all()

    assert [c.title for c in chapters] == ["제1장 바람이 바뀌던 날", "제2장 낮게 뜬 불빛"]
    assert book.total_paragraphs == len(paragraphs) == 5
    assert book.total_sentences == len(sentences) == 11
    assert [s.global_seq for s in sentences] == list(range(11))
    assert [p.scene_break_before for p in paragraphs] == [False, False, True, False, False]
    assert [p.sequence for p in paragraphs] == [0, 1, 2, 0, 1]  # per chapter

    # Chapter and paragraph sentence ranges are contiguous and consistent.
    assert (chapters[0].first_sentence_seq, chapters[0].sentence_count) == (0, 6)
    assert (chapters[1].first_sentence_seq, chapters[1].sentence_count) == (6, 5)
    for paragraph in paragraphs:
        own = [s for s in sentences if s.paragraph_id == paragraph.id]
        assert [s.sentence_index for s in own] == list(range(paragraph.sentence_count))
        assert own[0].global_seq == paragraph.first_sentence_seq
        for sentence in own:
            assert paragraph.text[sentence.char_start : sentence.char_end] == sentence.text
    assert [s.text for s in sentences[8:10]] == ['"누구 있어요? 대답해 주세요!"', "하람이 외쳤다."]


async def test_ingest_epub_book(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, build_epub(SAMPLE_EPUB_DOCS), source_format="epub")
    outcome = await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    assert outcome.status == "ready"
    async with db.sessionmaker() as session:
        sections = await session.scalar(select(func.count()).select_from(Section))
    assert sections == 3  # ch1 (1), ch2 (untitled + "병 속의 편지")


async def test_rights_are_rechecked_in_the_worker(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, SAMPLE_TEXT, ai_processing_rights=False)
    outcome = await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    assert (outcome.status, outcome.error) == ("failed", "rights_insufficient")
    async with db.sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Paragraph)) == 0


async def test_parse_errors_mark_the_book_failed_with_a_code(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, "등대".encode("cp949"))
    outcome = await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    assert outcome.error == "invalid_text_encoding"
    async with db.sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book is not None and book.status == BookStatus.FAILED
        assert book.processing_error == "invalid_text_encoding"


async def test_duplicate_or_stale_jobs_are_skipped(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, SAMPLE_TEXT)
    assert (
        await ingest_book(db.sessionmaker, storage, book_id, expected_version=0, today=lambda: TODAY)
    ).status == "ready"
    # At-least-once delivery re-runs the same message: it must not reprocess.
    again = await ingest_book(db.sessionmaker, storage, book_id, expected_version=0, today=lambda: TODAY)
    assert again.status == "skipped"
    assert (
        await ingest_book(db.sessionmaker, storage, uuid.uuid4(), today=lambda: TODAY)
    ).status == "missing"


async def test_reprocessing_keeps_reading_positions(db: Db, storage) -> None:  # type: ignore[no-untyped-def]
    book_id = await create_book(db, storage, SAMPLE_TEXT)
    await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    user_id = await create_user(db)

    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await service.open(user_id, book_id)
        target = (await session.execute(select(Paragraph).where(Paragraph.global_seq == 3))).scalar_one()
        view = await service.update_position(
            user_id,
            view.session.id,
            paragraph_id=target.id,
            sentence_index=1,
            expected_version=1,
            updated_by="test",
        )
        assert view.position.sentence_global_seq == 7
        session_id, old_paragraph = view.session.id, target.id

    async with db.sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book is not None
        book.status = BookStatus.QUEUED
        await session.commit()
    assert (await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)).status == "ready"

    async with db.sessionmaker() as session:
        position = await session.get(ReadingPosition, session_id)
        assert position is not None
        new_paragraph = await session.get(Paragraph, position.paragraph_id)
        assert position.paragraph_id != old_paragraph  # content rows were replaced
        assert new_paragraph is not None and new_paragraph.global_seq == 3
        assert (position.sentence_index, position.sentence_global_seq) == (1, 7)
        assert position.position_version == 3  # bumped so stale clients refetch
