import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator
from story_core.books.rights import RightsType

from app.schemas.common import StrictRequest


class RightsInput(StrictRequest):
    rights_type: RightsType
    rights_holder: str | None = Field(default=None, max_length=200)
    license_start: date | None = None
    license_end: date | None = None
    commercial_use: bool
    audio_rights: bool
    ai_processing_rights: bool
    territory: str | None = Field(default=None, max_length=64)
    contract_ref: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _period(self) -> Self:
        if self.license_start and self.license_end and self.license_end < self.license_start:
            raise ValueError("license_end must not be before license_start")
        return self


class BookMetadataInput(StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    language: str = Field(default="ko", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    description: str | None = Field(default=None, max_length=5000)
    rights: RightsInput


class RightsResponse(BaseModel):
    rights_type: RightsType
    rights_holder: str | None
    license_start: date | None
    license_end: date | None
    commercial_use: bool
    audio_rights: bool
    ai_processing_rights: bool
    territory: str | None
    contract_ref: str | None
    verified_at: datetime | None


class AdminBookResponse(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None
    language: str
    description: str | None
    status: str
    processing_error: str | None
    processing_version: int
    source_format: str
    source_byte_size: int
    total_paragraphs: int
    total_sentences: int
    created_at: datetime
    processed_at: datetime | None
    rights: RightsResponse
    rights_problems: list[str]


class AdminBookListResponse(BaseModel):
    items: list[AdminBookResponse]


class BookSummary(BaseModel):
    id: uuid.UUID
    title: str
    author: str | None
    language: str
    total_sentences: int


class BookListResponse(BaseModel):
    items: list[BookSummary]
    total: int
    limit: int
    offset: int


class ChapterOutline(BaseModel):
    id: uuid.UUID
    sequence: int
    title: str
    first_sentence_seq: int
    sentence_count: int


class BookDetailResponse(BookSummary):
    description: str | None
    total_paragraphs: int
    chapters: list[ChapterOutline]


class ParagraphResponse(BaseModel):
    id: uuid.UUID
    sequence: int
    global_seq: int
    first_sentence_seq: int
    scene_break_before: bool
    sentences: list[str]


class ChapterContentResponse(ChapterOutline):
    book_id: uuid.UUID
    paragraphs: list[ParagraphResponse]
