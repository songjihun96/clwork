"""Reader-facing book queries. Only books that are processed *and* currently licensed are visible."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from story_core.books.rights import RightsType
from story_core.models.book import Book, BookRights, BookStatus, Chapter, Paragraph, Sentence


def readable_condition(today: date) -> ColumnElement[bool]:
    """SQL twin of ``rights_problems(...) == []`` plus ``status == ready`` (kept in sync by tests)."""
    return and_(
        Book.status == BookStatus.READY,
        BookRights.commercial_use.is_(True),
        BookRights.audio_rights.is_(True),
        BookRights.ai_processing_rights.is_(True),
        or_(
            BookRights.rights_type == RightsType.PUBLIC_DOMAIN,
            and_(BookRights.rights_holder.is_not(None), func.trim(BookRights.rights_holder) != ""),
        ),
        or_(BookRights.rights_type != RightsType.LICENSED, BookRights.license_start.is_not(None)),
        or_(BookRights.license_start.is_(None), BookRights.license_start <= today),
        or_(BookRights.license_end.is_(None), BookRights.license_end >= today),
    )


@dataclass(frozen=True, slots=True)
class ParagraphContent:
    id: uuid.UUID
    sequence: int
    global_seq: int
    first_sentence_seq: int
    scene_break_before: bool
    sentences: list[str]


@dataclass(frozen=True, slots=True)
class ChapterContent:
    chapter: Chapter
    paragraphs: list[ParagraphContent]


class BookCatalog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_readable(self, today: date, *, limit: int, offset: int) -> tuple[list[Book], int]:
        base = select(Book).join(BookRights, BookRights.book_id == Book.id).where(readable_condition(today))
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        result = await self._session.execute(base.order_by(Book.title, Book.id).limit(limit).offset(offset))
        return list(result.scalars()), int(total or 0)

    async def get_readable(self, book_id: uuid.UUID, today: date) -> Book | None:
        result = await self._session.execute(
            select(Book)
            .join(BookRights, BookRights.book_id == Book.id)
            .where(Book.id == book_id, readable_condition(today))
        )
        return result.scalar_one_or_none()

    async def chapters(self, book_id: uuid.UUID) -> list[Chapter]:
        result = await self._session.execute(
            select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.sequence)
        )
        return list(result.scalars())

    async def chapter_content(self, book_id: uuid.UUID, chapter_id: uuid.UUID) -> ChapterContent | None:
        chapter = await self._session.scalar(
            select(Chapter).where(Chapter.id == chapter_id, Chapter.book_id == book_id)
        )
        if chapter is None:
            return None
        paragraphs = (
            await self._session.execute(
                select(Paragraph).where(Paragraph.chapter_id == chapter_id).order_by(Paragraph.sequence)
            )
        ).scalars()
        sentence_rows = await self._session.execute(
            select(Sentence.paragraph_id, Sentence.text)
            .join(Paragraph, Paragraph.id == Sentence.paragraph_id)
            .where(Paragraph.chapter_id == chapter_id)
            .order_by(Sentence.global_seq)
        )
        by_paragraph: dict[uuid.UUID, list[str]] = {}
        for paragraph_id, text in sentence_rows.all():
            by_paragraph.setdefault(paragraph_id, []).append(text)
        return ChapterContent(
            chapter=chapter,
            paragraphs=[
                ParagraphContent(
                    id=p.id,
                    sequence=p.sequence,
                    global_seq=p.global_seq,
                    first_sentence_seq=p.first_sentence_seq,
                    scene_break_before=p.scene_break_before,
                    sentences=by_paragraph.get(p.id, []),
                )
                for p in paragraphs
            ],
        )
