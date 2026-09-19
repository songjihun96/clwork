"""Reader-facing book endpoints. Only processed, currently licensed books are visible."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from story_core.books.catalog import BookCatalog
from story_core.books.rights import rights_today

from app.core.errors import NotFound
from app.dependencies import CurrentUserDep, DbSession
from app.schemas.books import (
    BookDetailResponse,
    BookListResponse,
    BookSummary,
    ChapterContentResponse,
    ChapterOutline,
    ParagraphResponse,
)
from app.schemas.common import ERROR_RESPONSES, ErrorResponse

router = APIRouter(prefix="/books", tags=["books"])

_NOT_FOUND = {**ERROR_RESPONSES, 404: {"model": ErrorResponse}}


@router.get("", response_model=BookListResponse, responses=ERROR_RESPONSES)
async def list_books(
    _: CurrentUserDep,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> BookListResponse:
    books, total = await BookCatalog(session).list_readable(rights_today(), limit=limit, offset=offset)
    return BookListResponse(
        items=[
            BookSummary(
                id=b.id,
                title=b.title,
                author=b.author,
                language=b.language,
                total_sentences=b.total_sentences,
            )
            for b in books
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{book_id}", response_model=BookDetailResponse, responses=_NOT_FOUND)
async def get_book(book_id: uuid.UUID, _: CurrentUserDep, session: DbSession) -> BookDetailResponse:
    catalog = BookCatalog(session)
    book = await catalog.get_readable(book_id, rights_today())
    if book is None:
        raise NotFound("Book not found")
    chapters = await catalog.chapters(book_id)
    return BookDetailResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        language=book.language,
        total_sentences=book.total_sentences,
        description=book.description,
        total_paragraphs=book.total_paragraphs,
        chapters=[
            ChapterOutline(
                id=c.id,
                sequence=c.sequence,
                title=c.title,
                first_sentence_seq=c.first_sentence_seq,
                sentence_count=c.sentence_count,
            )
            for c in chapters
        ],
    )


@router.get("/{book_id}/chapters/{chapter_id}", response_model=ChapterContentResponse, responses=_NOT_FOUND)
async def get_chapter(
    book_id: uuid.UUID, chapter_id: uuid.UUID, _: CurrentUserDep, session: DbSession
) -> ChapterContentResponse:
    catalog = BookCatalog(session)
    if await catalog.get_readable(book_id, rights_today()) is None:
        raise NotFound("Book not found")
    content = await catalog.chapter_content(book_id, chapter_id)
    if content is None:
        raise NotFound("Chapter not found")
    chapter = content.chapter
    return ChapterContentResponse(
        id=chapter.id,
        book_id=book_id,
        sequence=chapter.sequence,
        title=chapter.title,
        first_sentence_seq=chapter.first_sentence_seq,
        sentence_count=chapter.sentence_count,
        paragraphs=[
            ParagraphResponse(
                id=p.id,
                sequence=p.sequence,
                global_seq=p.global_seq,
                first_sentence_seq=p.first_sentence_seq,
                scene_break_before=p.scene_break_before,
                sentences=p.sentences,
            )
            for p in content.paragraphs
        ],
    )
