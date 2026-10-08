import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import StrictRequest


class ParagraphAudioRequest(StrictRequest):
    # Current paragraph plus a small lookahead; the client asks again as reading advances.
    paragraph_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)


class SentenceTiming(BaseModel):
    sentence_index: int
    start_ms: int
    end_ms: int


class AudioFile(BaseModel):
    url: str
    expires_at: datetime
    format: Literal["wav", "aac"]
    duration_ms: int
    sentence_timings: list[SentenceTiming]


class ParagraphAudioItem(BaseModel):
    paragraph_id: uuid.UUID
    # ready: audio available now · pending: rendering was requested, ask again · unavailable: not in this book
    status: Literal["ready", "pending", "unavailable"]
    audio: AudioFile | None = None


class ParagraphAudioResponse(BaseModel):
    items: list[ParagraphAudioItem]
    retry_after_ms: int | None = None
