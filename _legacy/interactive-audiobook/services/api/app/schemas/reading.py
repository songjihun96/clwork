import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator
from story_core.models.reading import SpoilerMode
from story_core.reading.sessions import PlaybackAction, SessionView
from story_core.reading.state_machine import ReadingState

from app.schemas.common import StrictRequest


class OpenSessionRequest(StrictRequest):
    book_id: uuid.UUID


class SessionBook(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None
    total_sentences: int


class PositionResponse(BaseModel):
    chapter_id: uuid.UUID | None
    paragraph_id: uuid.UUID | None
    sentence_index: int
    sentence_global_seq: int
    position_version: int
    updated_at: datetime


class ReadingSessionResponse(BaseModel):
    id: uuid.UUID
    book: SessionBook
    playback_state: ReadingState
    spoiler_mode: SpoilerMode
    speed: float
    max_read_seq: int
    progress: float
    position: PositionResponse
    created_at: datetime
    last_active_at: datetime

    @classmethod
    def from_view(cls, view: SessionView) -> "ReadingSessionResponse":
        s, p, b = view.session, view.position, view.book
        return cls(
            id=s.id,
            book=SessionBook(id=b.id, title=b.title, author=b.author, total_sentences=b.total_sentences),
            playback_state=ReadingState(s.playback_state),
            spoiler_mode=SpoilerMode(s.spoiler_mode),
            speed=s.speed,
            max_read_seq=s.max_read_seq,
            progress=view.progress,
            position=PositionResponse(
                chapter_id=p.chapter_id,
                paragraph_id=p.paragraph_id,
                sentence_index=p.sentence_index,
                sentence_global_seq=p.sentence_global_seq,
                position_version=p.position_version,
                updated_at=p.updated_at,
            ),
            created_at=s.created_at,
            last_active_at=s.last_active_at,
        )


class ReadingSessionListResponse(BaseModel):
    items: list[ReadingSessionResponse]


class PositionUpdate(StrictRequest):
    paragraph_id: uuid.UUID
    sentence_index: int = Field(ge=0, le=10_000)
    expected_version: int = Field(ge=1)


class UpdateSessionRequest(StrictRequest):
    position: PositionUpdate | None = None
    spoiler_mode: SpoilerMode | None = None
    speed: float | None = Field(default=None, ge=0.5, le=3.0)

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.position is None and self.spoiler_mode is None and self.speed is None:
            raise ValueError("at least one field must be provided")
        return self


class PlaybackRequest(StrictRequest):
    action: PlaybackAction
