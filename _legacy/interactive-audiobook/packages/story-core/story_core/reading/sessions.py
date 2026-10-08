"""Reading session use cases shared by the API (Listen mode) and, later, the realtime agent.

Ownership is enforced here: every method takes ``user_id`` and a session belonging to another user
is reported as not found. Position writes use optimistic concurrency (``position_version``) so two
devices cannot silently overwrite each other.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from story_core.books.catalog import BookCatalog, readable_condition
from story_core.books.rights import rights_today
from story_core.models.book import Book, BookRights, Paragraph
from story_core.models.reading import ReadingPosition, ReadingSession, SpoilerMode
from story_core.reading.state_machine import (
    Event,
    EventType,
    MachineConfig,
    Position,
    ReadingState,
    Snapshot,
    transition,
)
from story_core.time import utcnow

# Listen mode (no realtime agent): resume without the spoken bridge phrase.
LISTEN_MODE = MachineConfig(bridge_phrase=False)

_TALK_ONLY_STATES = frozenset(
    {
        ReadingState.USER_SPEAKING,
        ReadingState.PROCESSING_QUESTION,
        ReadingState.ANSWERING,
        ReadingState.AWAITING_FOLLOWUP,
        ReadingState.RESUMING,
        ReadingState.PREPARING,
    }
)


class ReadingError(Exception):
    code = "reading_error"


class SessionNotFound(ReadingError):
    code = "session_not_found"


class BookUnavailable(ReadingError):
    code = "book_unavailable"


class InvalidPosition(ReadingError):
    code = "invalid_position"


class PositionConflict(ReadingError):
    code = "position_conflict"


class PlaybackActionRejected(ReadingError):
    code = "playback_action_rejected"


class PlaybackAction(StrEnum):
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class SessionView:
    session: ReadingSession
    position: ReadingPosition
    book: Book

    @property
    def progress(self) -> float:
        total = self.book.total_sentences
        return 0.0 if total <= 0 else min(1.0, (self.position.sentence_global_seq + 1) / total)


class ReadingSessionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        today: Callable[[], date] = rights_today,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._db = session
        self._today = today
        self._clock = clock
        self._catalog = BookCatalog(session)

    # ------------------------------------------------------------------ queries

    async def get(self, user_id: uuid.UUID, session_id: uuid.UUID) -> SessionView:
        row = (
            await self._db.execute(
                select(ReadingSession, ReadingPosition, Book)
                .join(ReadingPosition, ReadingPosition.session_id == ReadingSession.id)
                .join(Book, Book.id == ReadingSession.book_id)
                .where(ReadingSession.id == session_id, ReadingSession.user_id == user_id)
                # Bulk UPDATEs bypass the identity map; always return current row values.
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None:
            raise SessionNotFound
        return SessionView(row[0], row[1], row[2])

    async def for_agent(self, session_id: uuid.UUID) -> SessionView | None:
        """Load a session **without** a user id.

        Server-side only, for the realtime agent: it is dispatched with a session id and no credentials of
        its own, so it looks the session up and then re-authorises from what it finds (book state, rights).
        Never reachable from a request — API handlers always go through ``get(user_id, session_id)``.
        """
        row = (
            await self._db.execute(
                select(ReadingSession, ReadingPosition, Book)
                .join(ReadingPosition, ReadingPosition.session_id == ReadingSession.id)
                .join(Book, Book.id == ReadingSession.book_id)
                .where(ReadingSession.id == session_id, ReadingSession.ended_at.is_(None))
                .execution_options(populate_existing=True)
            )
        ).first()
        return SessionView(row[0], row[1], row[2]) if row is not None else None

    async def list_active(self, user_id: uuid.UUID, *, limit: int = 20) -> list[SessionView]:
        rows = await self._db.execute(
            select(ReadingSession, ReadingPosition, Book)
            .join(ReadingPosition, ReadingPosition.session_id == ReadingSession.id)
            .join(Book, Book.id == ReadingSession.book_id)
            .join(BookRights, BookRights.book_id == Book.id)
            # Books whose licence lapsed disappear from "continue listening"; the session row is kept.
            .where(
                ReadingSession.user_id == user_id,
                ReadingSession.ended_at.is_(None),
                readable_condition(self._today()),
            )
            .order_by(ReadingSession.last_active_at.desc())
            .limit(limit)
        )
        return [SessionView(r[0], r[1], r[2]) for r in rows.all()]

    # ------------------------------------------------------------------ commands

    async def open(self, user_id: uuid.UUID, book_id: uuid.UUID) -> tuple[SessionView, bool]:
        """Returns the active session for this book, creating it at the first sentence if needed."""
        book = await self._catalog.get_readable(book_id, self._today())
        if book is None:
            raise BookUnavailable
        existing = await self._active_session_id(user_id, book_id)
        if existing is not None:
            return await self.get(user_id, existing), False

        first = (
            await self._db.execute(
                select(Paragraph.id, Paragraph.chapter_id)
                .where(Paragraph.book_id == book_id)
                .order_by(Paragraph.global_seq)
                .limit(1)
            )
        ).first()
        if first is None:
            raise BookUnavailable

        now = self._clock()
        reading_session = ReadingSession(
            id=uuid.uuid4(), user_id=user_id, book_id=book_id, last_active_at=now, created_at=now
        )
        try:
            self._db.add(reading_session)
            await self._db.flush()
            self._db.add(
                ReadingPosition(
                    session_id=reading_session.id,
                    chapter_id=first.chapter_id,
                    paragraph_id=first.id,
                    sentence_index=0,
                    sentence_global_seq=0,
                    position_version=1,
                    updated_by="open",
                    updated_at=now,
                )
            )
            await self._db.commit()
        except IntegrityError:
            # A concurrent request created the session first.
            await self._db.rollback()
            existing = await self._active_session_id(user_id, book_id)
            if existing is None:
                raise
            return await self.get(user_id, existing), False
        return await self.get(user_id, reading_session.id), True

    async def update_position(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        paragraph_id: uuid.UUID,
        sentence_index: int,
        expected_version: int,
        updated_by: str,
    ) -> SessionView:
        view = await self.get(user_id, session_id)
        paragraph = (
            await self._db.execute(
                select(Paragraph.chapter_id, Paragraph.first_sentence_seq, Paragraph.sentence_count).where(
                    Paragraph.id == paragraph_id, Paragraph.book_id == view.session.book_id
                )
            )
        ).first()
        if paragraph is None or not 0 <= sentence_index < paragraph.sentence_count:
            raise InvalidPosition

        global_seq = paragraph.first_sentence_seq + sentence_index
        now = self._clock()
        result = await self._db.execute(
            update(ReadingPosition)
            .where(
                ReadingPosition.session_id == session_id, ReadingPosition.position_version == expected_version
            )
            .values(
                chapter_id=paragraph.chapter_id,
                paragraph_id=paragraph_id,
                sentence_index=sentence_index,
                sentence_global_seq=global_seq,
                position_version=ReadingPosition.position_version + 1,
                updated_by=updated_by[:64],
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            # Nothing was written (version mismatch), so no rollback: that would expire the caller's objects.
            raise PositionConflict
        await self._db.execute(
            update(ReadingSession)
            .where(ReadingSession.id == session_id)
            .values(
                last_active_at=now,
                max_read_seq=_greatest(view.session.max_read_seq, global_seq),
            )
            .execution_options(synchronize_session=False)
        )
        await self._db.commit()
        return await self.get(user_id, session_id)

    async def update_settings(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        spoiler_mode: SpoilerMode | None = None,
        speed: float | None = None,
    ) -> SessionView:
        view = await self.get(user_id, session_id)
        if spoiler_mode is not None:
            view.session.spoiler_mode = spoiler_mode
        if speed is not None:
            view.session.speed = speed
        view.session.last_active_at = self._clock()
        await self._db.commit()
        return await self.get(user_id, session_id)

    async def apply_playback(
        self, user_id: uuid.UUID, session_id: uuid.UUID, action: PlaybackAction
    ) -> SessionView:
        view = await self.get(user_id, session_id)
        snapshot = snapshot_from_storage(view.session.playback_state, view.position)

        if action is PlaybackAction.PLAY:
            if snapshot.state is ReadingState.READING:
                return view
            events: list[Event]
            if snapshot.state in (ReadingState.IDLE, ReadingState.ERROR):
                start = EventType.START if snapshot.state is ReadingState.IDLE else EventType.RETRY
                events = [Event(start), Event(EventType.READY, position=snapshot.resume_position)]
            else:
                events = [Event(EventType.CONTROL_RESUME)]
        elif action is PlaybackAction.PAUSE:
            events = [Event(EventType.CONTROL_PAUSE)]
        else:
            events = [Event(EventType.CONTROL_STOP)]

        for event in events:
            step = transition(snapshot, event, LISTEN_MODE)
            if step.ignored:
                raise PlaybackActionRejected
            snapshot = step.snapshot

        view.session.playback_state = snapshot.state
        view.session.last_active_at = self._clock()
        await self._db.commit()
        return await self.get(user_id, session_id)

    # ------------------------------------------------------------------ helpers

    async def _active_session_id(self, user_id: uuid.UUID, book_id: uuid.UUID) -> uuid.UUID | None:
        found: uuid.UUID | None = await self._db.scalar(
            select(ReadingSession.id).where(
                ReadingSession.user_id == user_id,
                ReadingSession.book_id == book_id,
                ReadingSession.ended_at.is_(None),
            )
        )
        return found


def _greatest(current: int, candidate: int) -> int:
    return candidate if candidate > current else current


def snapshot_from_storage(playback_state: str, position: ReadingPosition) -> Snapshot:
    """Rebuilds a state-machine snapshot from persisted data.

    Talk-mode states are never resumed from storage (the agent that owned them is gone): they
    recover as PAUSED at the last confirmed sentence (docs/realtime.md §7).
    """
    state = ReadingState(playback_state)
    pos = (
        Position(paragraph_id=str(position.paragraph_id), sentence_index=position.sentence_index)
        if position.paragraph_id is not None
        else None
    )
    if state in _TALK_ONLY_STATES:
        state = ReadingState.PAUSED
    if state is ReadingState.PAUSED:
        return Snapshot(state=state, position=pos, interrupt_point=pos)
    return Snapshot(state=state, position=pos)
