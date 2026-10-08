"""Book ingestion: stored source file → chapters / sections / paragraphs / sentences.

Runs in the worker (task ``books.ingest``). Idempotent: content is replaced as a whole inside one
transaction, and a job carrying a stale ``expected_version`` is skipped, so at-least-once delivery
and manual re-runs are safe. Existing reading positions are re-attached by sentence ``global_seq``.

Embedding (RAG) is added to this pipeline in Phase 4.
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from story_core.books.rights import RightsTerms, RightsType, rights_problems, rights_today
from story_core.ingestion.epub_parser import parse_epub
from story_core.ingestion.parsed import IngestionError, ParsedBook
from story_core.ingestion.sentences import RuleBasedKoreanSplitter, SentenceSplitter
from story_core.ingestion.text_parser import parse_text
from story_core.models.book import (
    Book,
    BookRights,
    BookStatus,
    Chapter,
    Paragraph,
    Section,
    Sentence,
    SourceFormat,
)
from story_core.models.reading import ReadingPosition, ReadingSession
from story_core.storage.base import ObjectNotFound, StorageProvider
from story_core.time import utcnow

logger = logging.getLogger(__name__)

MAX_PARAGRAPHS = 100_000
MAX_SENTENCES = 500_000
_INSERT_BATCH = 1_000


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: str
    error: str | None = None
    paragraphs: int = 0
    sentences: int = 0


@dataclass(slots=True)
class ContentRows:
    chapters: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    sentences: list[dict[str, Any]] = field(default_factory=list)
    # sentence global_seq -> (chapter_id, paragraph_id, sentence_index)
    locations: list[tuple[uuid.UUID, uuid.UUID, int]] = field(default_factory=list)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parse_source(data: bytes, source_format: str) -> ParsedBook:
    if source_format == SourceFormat.EPUB:
        return parse_epub(data)
    if source_format == SourceFormat.TXT:
        return parse_text(data)
    raise IngestionError("unsupported_format", f"Unsupported source format: {source_format}")


def build_rows(book_id: uuid.UUID, parsed: ParsedBook, splitter: SentenceSplitter) -> ContentRows:
    rows = ContentRows()
    paragraph_seq = 0
    for chapter_number, parsed_chapter in enumerate(parsed.chapters):
        chapter_id = uuid.uuid4()
        chapter_first_sentence = len(rows.sentences)
        paragraph_in_chapter = 0
        for section_number, parsed_section in enumerate(parsed_chapter.sections):
            section_id = uuid.uuid4()
            rows.sections.append(
                {
                    "id": section_id,
                    "book_id": book_id,
                    "chapter_id": chapter_id,
                    "sequence": section_number,
                    "title": (parsed_section.title or None) and parsed_section.title[:300],
                }
            )
            for parsed_paragraph in parsed_section.paragraphs:
                spans = splitter.split(parsed_paragraph.text)
                if not spans:
                    continue
                paragraph_id = uuid.uuid4()
                first_sentence = len(rows.sentences)
                for index, span in enumerate(spans):
                    rows.sentences.append(
                        {
                            "id": uuid.uuid4(),
                            "book_id": book_id,
                            "paragraph_id": paragraph_id,
                            "sentence_index": index,
                            "global_seq": first_sentence + index,
                            "text": span.text,
                            "text_hash": _sha256(span.text),
                            "char_start": span.start,
                            "char_end": span.end,
                        }
                    )
                    rows.locations.append((chapter_id, paragraph_id, index))
                rows.paragraphs.append(
                    {
                        "id": paragraph_id,
                        "book_id": book_id,
                        "chapter_id": chapter_id,
                        "section_id": section_id,
                        "sequence": paragraph_in_chapter,
                        "global_seq": paragraph_seq,
                        "text": parsed_paragraph.text,
                        "text_hash": _sha256(parsed_paragraph.text),
                        "char_count": len(parsed_paragraph.text),
                        "first_sentence_seq": first_sentence,
                        "sentence_count": len(spans),
                        "scene_break_before": parsed_paragraph.scene_break_before,
                    }
                )
                paragraph_seq += 1
                paragraph_in_chapter += 1
                if paragraph_seq > MAX_PARAGRAPHS or len(rows.sentences) > MAX_SENTENCES:
                    raise IngestionError("book_too_large", "The book exceeds the supported size")
        sentence_count = len(rows.sentences) - chapter_first_sentence
        if sentence_count == 0:
            rows.sections = [s for s in rows.sections if s["chapter_id"] != chapter_id]
            continue
        rows.chapters.append(
            {
                "id": chapter_id,
                "book_id": book_id,
                "sequence": len(rows.chapters),
                "title": parsed_chapter.title[:300] or f"{chapter_number + 1}장",
                "first_sentence_seq": chapter_first_sentence,
                "sentence_count": sentence_count,
            }
        )
    used_sections = {p["section_id"] for p in rows.paragraphs}
    rows.sections = [s for s in rows.sections if s["id"] in used_sections]
    if not rows.sentences:
        raise IngestionError("empty_book", "No readable sentences were found")
    return rows


def rights_terms(rights: BookRights) -> RightsTerms:
    return RightsTerms(
        rights_type=RightsType(rights.rights_type),
        rights_holder=rights.rights_holder,
        license_start=rights.license_start,
        license_end=rights.license_end,
        commercial_use=rights.commercial_use,
        audio_rights=rights.audio_rights,
        ai_processing_rights=rights.ai_processing_rights,
    )


async def _mark(sessionmaker: async_sessionmaker[AsyncSession], book_id: uuid.UUID, **values: Any) -> None:
    async with sessionmaker() as session:
        await session.execute(update(Book).where(Book.id == book_id).values(**values))
        await session.commit()


async def _bulk_insert(session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), _INSERT_BATCH):
        await session.execute(insert(model), rows[i : i + _INSERT_BATCH])


async def ingest_book(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: StorageProvider,
    book_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    splitter: SentenceSplitter | None = None,
    today: Callable[[], date] = rights_today,
    clock: Callable[[], datetime] = utcnow,
) -> IngestOutcome:
    splitter = splitter or RuleBasedKoreanSplitter()

    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        rights = await session.get(BookRights, book_id)
        if book is None:
            return IngestOutcome(status="missing")
        if expected_version is not None and book.processing_version != expected_version:
            logger.info("ingest_skipped_stale_job", extra={"book_id": str(book_id)})
            return IngestOutcome(status="skipped")
        if book.status not in (BookStatus.QUEUED, BookStatus.PROCESSING, BookStatus.FAILED):
            return IngestOutcome(status="skipped")
        if rights is None or rights_problems(rights_terms(rights), today()):
            book.status, book.processing_error = BookStatus.FAILED, "rights_insufficient"
            await session.commit()
            return IngestOutcome(status=BookStatus.FAILED, error="rights_insufficient")
        book.status, book.processing_error = BookStatus.PROCESSING, None
        source_key, source_format = book.source_storage_key, book.source_format
        await session.commit()

    try:
        data = await storage.get_bytes(source_key)
        rows = await asyncio.to_thread(
            lambda: build_rows(book_id, parse_source(data, source_format), splitter)
        )
    except (IngestionError, ObjectNotFound) as exc:
        code = exc.code if isinstance(exc, IngestionError) else "source_missing"
        await _mark(sessionmaker, book_id, status=BookStatus.FAILED, processing_error=code)
        logger.warning("ingest_failed", extra={"book_id": str(book_id), "error_code": code})
        return IngestOutcome(status=BookStatus.FAILED, error=code)
    except Exception:
        await _mark_failed_best_effort(sessionmaker, book_id)
        raise  # unexpected: let the queue retry (a FAILED book may be processed again)

    try:
        await _store_content(sessionmaker, book_id, rows, clock())
    except Exception:
        await _mark_failed_best_effort(sessionmaker, book_id)
        raise

    logger.info(
        "ingest_completed",
        extra={"book_id": str(book_id), "paragraphs": len(rows.paragraphs), "sentences": len(rows.sentences)},
    )
    return IngestOutcome(
        status=BookStatus.READY, paragraphs=len(rows.paragraphs), sentences=len(rows.sentences)
    )


async def _mark_failed_best_effort(
    sessionmaker: async_sessionmaker[AsyncSession], book_id: uuid.UUID
) -> None:
    try:
        await _mark(sessionmaker, book_id, status=BookStatus.FAILED, processing_error="internal_error")
    except Exception:
        logger.exception("ingest_mark_failed_error", extra={"book_id": str(book_id)})


async def _store_content(
    sessionmaker: async_sessionmaker[AsyncSession], book_id: uuid.UUID, rows: ContentRows, now: datetime
) -> None:
    async with sessionmaker() as session:
        await session.execute(delete(Chapter).where(Chapter.book_id == book_id))
        await _bulk_insert(session, Chapter, rows.chapters)
        await _bulk_insert(session, Section, rows.sections)
        await _bulk_insert(session, Paragraph, rows.paragraphs)
        await _bulk_insert(session, Sentence, rows.sentences)
        await _reattach_positions(session, book_id, rows, now)
        await session.execute(
            update(Book)
            .where(Book.id == book_id)
            .values(
                status=BookStatus.READY,
                processing_error=None,
                processing_version=Book.processing_version + 1,
                processed_at=now,
                total_paragraphs=len(rows.paragraphs),
                total_sentences=len(rows.sentences),
            )
        )
        await session.commit()


async def _reattach_positions(
    session: AsyncSession, book_id: uuid.UUID, rows: ContentRows, now: datetime
) -> None:
    result = await session.execute(
        select(ReadingPosition.session_id, ReadingPosition.sentence_global_seq)
        .join(ReadingSession, ReadingSession.id == ReadingPosition.session_id)
        .where(ReadingSession.book_id == book_id)
    )
    last = len(rows.locations) - 1
    updates = []
    for session_id, global_seq in result.all():
        seq = min(max(global_seq, 0), last)
        chapter_id, paragraph_id, sentence_index = rows.locations[seq]
        updates.append(
            {
                "session_id": session_id,
                "chapter_id": chapter_id,
                "paragraph_id": paragraph_id,
                "sentence_index": sentence_index,
                "sentence_global_seq": seq,
                "updated_by": "reprocessing",
                "updated_at": now,
            }
        )
    if updates:
        # Bulk UPDATE by primary key; bumps the version so clients holding an old one refetch.
        await session.execute(update(ReadingPosition), updates)
        await session.execute(
            update(ReadingPosition)
            .where(ReadingPosition.session_id.in_([u["session_id"] for u in updates]))
            .values(position_version=ReadingPosition.position_version + 1)
        )
