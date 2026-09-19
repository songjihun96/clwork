import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from story_core.books.catalog import BookCatalog
from story_core.books.rights import RightsProblem, RightsTerms, RightsType, rights_problems, rights_today
from story_core.ingestion.pipeline import ingest_book
from story_core.models import BookRights, BookStatus, Paragraph, ReadingSession
from story_core.reading.sessions import (
    BookUnavailable,
    InvalidPosition,
    PlaybackAction,
    PlaybackActionRejected,
    PositionConflict,
    ReadingSessionService,
    SessionNotFound,
    snapshot_from_storage,
)
from story_core.reading.state_machine import ReadingState
from story_core.storage.base import StorageError
from story_core.storage.local import LocalFileStorage
from tests.conftest import SAMPLE_TEXT, TODAY, Db, create_book, create_user


async def ready_book(db: Db, storage: LocalFileStorage, **rights: object) -> uuid.UUID:
    book_id = await create_book(db, storage, SAMPLE_TEXT)
    await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    if rights:
        async with db.sessionmaker() as session:
            row = await session.get(BookRights, book_id)
            for key, value in rights.items():
                setattr(row, key, value)
            await session.commit()
    return book_id


# ---------------------------------------------------------------- rights


def test_rights_problems() -> None:
    ok = RightsTerms(RightsType.LICENSED, "출판사", TODAY - timedelta(days=1), TODAY, True, True, True)
    assert rights_problems(ok, TODAY) == []
    expired = RightsTerms(RightsType.LICENSED, "출판사", date(2020, 1, 1), date(2025, 1, 1), True, True, True)
    assert rights_problems(expired, TODAY) == [RightsProblem.LICENSE_EXPIRED]
    ebook_only = RightsTerms(RightsType.LICENSED, "출판사", date(2020, 1, 1), None, True, False, False)
    assert set(rights_problems(ebook_only, TODAY)) == {
        RightsProblem.AUDIO_RIGHTS_MISSING,
        RightsProblem.AI_PROCESSING_RIGHTS_MISSING,
    }
    public = RightsTerms(RightsType.PUBLIC_DOMAIN, None, None, None, True, True, True)
    assert rights_problems(public, TODAY) == []
    no_holder = RightsTerms(RightsType.OWNED, "  ", None, None, True, True, True)
    assert rights_problems(no_holder, TODAY) == [RightsProblem.RIGHTS_HOLDER_MISSING]


_optional_date = st.one_of(st.none(), st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 12, 31)))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    rights_type=st.sampled_from(list(RightsType)),
    holder=st.sampled_from([None, "", " ", "출판사"]),
    start=_optional_date,
    end=_optional_date,
    flags=st.tuples(st.booleans(), st.booleans(), st.booleans()),
)
async def test_sql_readability_filter_matches_python_rules(
    tmp_path: Path,
    rights_type: RightsType,
    holder: str | None,
    start: date | None,
    end: date | None,
    flags: tuple[bool, bool, bool],
) -> None:
    """The SQL filter used by every reader query must agree with rights_problems()."""
    from story_core.db.session import DatabaseOptions, create_engine, create_sessionmaker
    from story_core.models import Base

    engine = create_engine(
        DatabaseOptions(
            url=f"sqlite+aiosqlite:///{tmp_path / f'{uuid.uuid4().hex}.db'}", application_name="t"
        )
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db = Db(engine, create_sessionmaker(engine))
    storage = LocalFileStorage(tmp_path / "s")
    try:
        commercial, audio, ai = flags
        book_id = await create_book(
            db,
            storage,
            b"x",
            status=BookStatus.READY,
            rights_type=rights_type,
            rights_holder=holder,
            license_start=start,
            license_end=end,
            commercial_use=commercial,
            audio_rights=audio,
            ai_processing_rights=ai,
        )
        terms = RightsTerms(rights_type, holder, start, end, commercial, audio, ai)
        async with db.sessionmaker() as session:
            visible = await BookCatalog(session).get_readable(book_id, TODAY) is not None
        assert visible == (rights_problems(terms, TODAY) == [])
    finally:
        await engine.dispose()


def test_licence_day_is_evaluated_in_the_contract_timezone() -> None:
    from datetime import UTC, datetime

    late_utc = datetime(2026, 9, 15, 18, 30, tzinfo=UTC)  # already 2026-09-16 03:30 in Seoul
    assert rights_today(late_utc) == date(2026, 9, 16)
    assert rights_today(late_utc, timezone="UTC") == date(2026, 9, 15)
    ended_yesterday_in_seoul = RightsTerms(
        RightsType.LICENSED, "출판사", date(2020, 1, 1), date(2026, 9, 15), True, True, True
    )
    assert rights_problems(ended_yesterday_in_seoul, rights_today(late_utc)) == [
        RightsProblem.LICENSE_EXPIRED
    ]


# ---------------------------------------------------------------- sessions


async def test_open_is_idempotent_and_starts_at_first_sentence(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    user_id = await create_user(db)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        first, created = await service.open(user_id, book_id)
        second, created_again = await service.open(user_id, book_id)
    assert created and not created_again
    assert first.session.id == second.session.id
    assert (first.position.sentence_global_seq, first.position.sentence_index) == (0, 0)
    assert first.session.playback_state == ReadingState.IDLE
    assert first.progress == pytest.approx(1 / 11)


async def test_sessions_are_private_to_their_owner(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    owner, other = await create_user(db), await create_user(db)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await service.open(owner, book_id)
        with pytest.raises(SessionNotFound):
            await service.get(other, view.session.id)
        with pytest.raises(SessionNotFound):
            await service.apply_playback(other, view.session.id, PlaybackAction.PLAY)
        assert await service.list_active(other) == []


async def test_unlicensed_or_unprocessed_books_cannot_be_opened(db: Db, storage: LocalFileStorage) -> None:
    user_id = await create_user(db)
    expired = await ready_book(db, storage, license_end=TODAY - timedelta(days=1))
    queued = await create_book(db, storage, SAMPLE_TEXT)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        for book_id in (expired, queued):
            with pytest.raises(BookUnavailable):
                await service.open(user_id, book_id)


async def test_position_update_validates_and_detects_conflicts(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    other_book = await ready_book(db, storage)
    user_id = await create_user(db)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await service.open(user_id, book_id)
        sid = view.session.id
        paragraphs = (
            (
                await session.execute(
                    select(Paragraph).where(Paragraph.book_id == book_id).order_by(Paragraph.global_seq)
                )
            )
            .scalars()
            .all()
        )
        foreign = (
            (await session.execute(select(Paragraph).where(Paragraph.book_id == other_book)))
            .scalars()
            .first()
        )
        assert foreign is not None

        moved = await service.update_position(
            user_id,
            sid,
            paragraph_id=paragraphs[1].id,
            sentence_index=1,
            expected_version=1,
            updated_by="device:a",
        )
        assert moved.position.position_version == 2
        assert moved.position.sentence_global_seq == 4
        assert moved.session.max_read_seq == 4

        # Another device still holding version 1 must not overwrite silently.
        with pytest.raises(PositionConflict):
            await service.update_position(
                user_id,
                sid,
                paragraph_id=paragraphs[0].id,
                sentence_index=0,
                expected_version=1,
                updated_by="device:b",
            )
        with pytest.raises(InvalidPosition):
            await service.update_position(
                user_id,
                sid,
                paragraph_id=paragraphs[1].id,
                sentence_index=99,
                expected_version=2,
                updated_by="x",
            )
        with pytest.raises(InvalidPosition):
            await service.update_position(
                user_id, sid, paragraph_id=foreign.id, sentence_index=0, expected_version=2, updated_by="x"
            )

        # Going back does not shrink the "already read" window used for spoiler filtering.
        back = await service.update_position(
            user_id,
            sid,
            paragraph_id=paragraphs[0].id,
            sentence_index=0,
            expected_version=2,
            updated_by="device:a",
        )
        assert back.position.sentence_global_seq == 0 and back.session.max_read_seq == 4


async def test_playback_actions_go_through_the_state_machine(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    user_id = await create_user(db)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await service.open(user_id, book_id)
        sid = view.session.id

        states = []
        for action in (
            PlaybackAction.PLAY,
            PlaybackAction.PLAY,
            PlaybackAction.PAUSE,
            PlaybackAction.PLAY,
            PlaybackAction.STOP,
        ):
            states.append((await service.apply_playback(user_id, sid, action)).session.playback_state)
        assert states == ["READING", "READING", "PAUSED", "READING", "IDLE"]

        with pytest.raises(PlaybackActionRejected):
            await service.apply_playback(user_id, sid, PlaybackAction.PAUSE)  # nothing to pause


async def test_talk_mode_state_left_by_a_crashed_agent_recovers_as_paused(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id = await ready_book(db, storage)
    user_id = await create_user(db)
    async with db.sessionmaker() as session:
        service = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await service.open(user_id, book_id)
        row = await session.get(ReadingSession, view.session.id)
        assert row is not None
        row.playback_state = ReadingState.ANSWERING
        await session.commit()

        snapshot = snapshot_from_storage(ReadingState.ANSWERING, view.position)
        assert snapshot.state is ReadingState.PAUSED and snapshot.interrupt_point is not None
        resumed = await service.apply_playback(user_id, view.session.id, PlaybackAction.PLAY)
        assert resumed.session.playback_state == ReadingState.READING


# ---------------------------------------------------------------- storage


async def test_local_storage_roundtrip_and_key_validation(storage: LocalFileStorage) -> None:
    await storage.put_bytes("books/abc/source/file.txt", b"hello", content_type="text/plain")
    assert await storage.exists("books/abc/source/file.txt")
    assert await storage.get_bytes("books/abc/source/file.txt") == b"hello"
    await storage.delete("books/abc/source/file.txt")
    assert not await storage.exists("books/abc/source/file.txt")
    for bad in ("../etc/passwd", "/abs", "a//b", "a/../../b", "a\\b", "dir/", ""):
        with pytest.raises(StorageError):
            await storage.put_bytes(bad, b"x", content_type="text/plain")
