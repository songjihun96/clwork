"""Content administration: upload, rights, processing requests."""

import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from story_core.books.rights import rights_problems, rights_today
from story_core.ingestion.epub_parser import looks_like_epub
from story_core.ingestion.parsed import IngestionError
from story_core.ingestion.pipeline import rights_terms
from story_core.ingestion.text_parser import decode_text
from story_core.jobs.queue import INGEST_BOOK_TASK, JobQueue
from story_core.models.book import Book, BookRights, BookStatus, SourceFormat
from story_core.storage.base import StorageProvider
from story_core.time import utcnow

from app.core.errors import AppError, Conflict, NotFound, ServiceUnavailable
from app.repositories.audit import AuditAction, AuditRepository
from app.schemas.books import AdminBookResponse, BookMetadataInput, RightsInput, RightsResponse
from app.security.uploads import UnsupportedMediaType

logger = logging.getLogger(__name__)

_PROCESSABLE = frozenset({BookStatus.UPLOADED, BookStatus.QUEUED, BookStatus.FAILED, BookStatus.READY})


class RightsInsufficient(AppError):
    status_code = 409
    code = "rights_insufficient"
    message = "Content rights do not allow processing"


def detect_format(data: bytes, declared_name: str | None) -> SourceFormat:
    """Content sniffing; the client's Content-Type and file name are only hints."""
    if looks_like_epub(data):
        return SourceFormat.EPUB
    if (declared_name or "").lower().endswith(".txt"):
        try:
            decode_text(data)
        except IngestionError as exc:
            raise UnsupportedMediaType(str(exc)) from exc
        return SourceFormat.TXT
    raise UnsupportedMediaType("Only EPUB and UTF-8 .txt files are supported")


class BookAdminService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageProvider,
        jobs: JobQueue,
        *,
        today: Callable[[], date] = rights_today,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._db = session
        self._storage = storage
        self._jobs = jobs
        self._today = today
        self._clock = clock
        self._audit = AuditRepository(session)

    async def create(
        self, *, admin_id: uuid.UUID, metadata: BookMetadataInput, data: bytes, source_format: SourceFormat
    ) -> AdminBookResponse:
        book_id = uuid.uuid4()
        digest = hashlib.sha256(data).hexdigest()
        key = f"books/{book_id}/source/{digest}.{source_format.value}"
        await self._storage.put_bytes(key, data, content_type="application/octet-stream")
        try:
            self._db.add(
                Book(
                    id=book_id,
                    title=metadata.title.strip(),
                    author=(metadata.author or "").strip() or None,
                    language=metadata.language,
                    description=metadata.description,
                    status=BookStatus.UPLOADED,
                    source_format=source_format,
                    source_storage_key=key,
                    source_sha256=digest,
                    source_byte_size=len(data),
                    created_by=admin_id,
                )
            )
            await self._db.flush()
            self._db.add(self._rights_row(book_id, metadata.rights, admin_id))
            self._audit.record(
                AuditAction.BOOK_UPLOADED,
                actor_user_id=admin_id,
                target_type="book",
                target_id=str(book_id),
                details={"format": source_format.value, "bytes": len(data)},
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            await self._storage.delete(key)  # do not leave orphaned source files
            raise
        return await self.get(book_id)

    async def update_rights(
        self, *, admin_id: uuid.UUID, book_id: uuid.UUID, rights: RightsInput
    ) -> AdminBookResponse:
        row = await self._db.get(BookRights, book_id)
        if row is None:
            raise NotFound("Book not found")
        replacement = self._rights_row(book_id, rights, admin_id)
        for column in BookRights.__table__.columns.keys():
            if column not in ("book_id", "created_at", "updated_at"):
                setattr(row, column, getattr(replacement, column))
        self._audit.record(
            AuditAction.BOOK_RIGHTS_UPDATED,
            actor_user_id=admin_id,
            target_type="book",
            target_id=str(book_id),
        )
        await self._db.commit()
        return await self.get(book_id)

    async def request_processing(self, *, admin_id: uuid.UUID, book_id: uuid.UUID) -> AdminBookResponse:
        book = await self._db.get(Book, book_id, with_for_update=True)
        rights = await self._db.get(BookRights, book_id)
        if book is None or rights is None:
            raise NotFound("Book not found")
        problems = rights_problems(rights_terms(rights), self._today())
        if problems:
            raise RightsInsufficient(f"Content rights do not allow processing: {', '.join(problems)}")
        if book.status not in _PROCESSABLE:
            raise Conflict("The book is already being processed", code="already_processing")

        book.status = BookStatus.QUEUED
        book.processing_error = None
        expected_version = book.processing_version
        self._audit.record(
            AuditAction.BOOK_PROCESSING_REQUESTED,
            actor_user_id=admin_id,
            target_type="book",
            target_id=str(book_id),
        )
        await self._db.commit()

        try:
            await self._jobs.enqueue(
                INGEST_BOOK_TASK, book_id=str(book_id), expected_version=expected_version
            )
        except Exception as exc:
            # The book stays "queued"; re-requesting processing is safe (the job is idempotent).
            logger.error("enqueue_failed", extra={"book_id": str(book_id), "exc_type": type(exc).__name__})
            raise ServiceUnavailable("Job queue unavailable, retry later", code="queue_unavailable") from exc
        return await self.get(book_id)

    async def get(self, book_id: uuid.UUID) -> AdminBookResponse:
        row = (
            await self._db.execute(
                select(Book, BookRights)
                .join(BookRights, BookRights.book_id == Book.id)
                .where(Book.id == book_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None:
            raise NotFound("Book not found")
        return self._response(row[0], row[1])

    async def list(self, *, limit: int, offset: int) -> list[AdminBookResponse]:
        rows = await self._db.execute(
            select(Book, BookRights)
            .join(BookRights, BookRights.book_id == Book.id)
            .order_by(Book.created_at.desc(), Book.id)
            .limit(limit)
            .offset(offset)
        )
        return [self._response(book, rights) for book, rights in rows.all()]

    def _rights_row(self, book_id: uuid.UUID, rights: RightsInput, admin_id: uuid.UUID) -> BookRights:
        return BookRights(
            book_id=book_id,
            rights_type=rights.rights_type,
            rights_holder=(rights.rights_holder or "").strip() or None,
            license_start=rights.license_start,
            license_end=rights.license_end,
            commercial_use=rights.commercial_use,
            audio_rights=rights.audio_rights,
            ai_processing_rights=rights.ai_processing_rights,
            territory=rights.territory,
            contract_ref=rights.contract_ref,
            verified_by=admin_id,
            verified_at=self._clock(),
        )

    def _response(self, book: Book, rights: BookRights) -> AdminBookResponse:
        return AdminBookResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            language=book.language,
            description=book.description,
            status=book.status,
            processing_error=book.processing_error,
            processing_version=book.processing_version,
            source_format=book.source_format,
            source_byte_size=book.source_byte_size,
            total_paragraphs=book.total_paragraphs,
            total_sentences=book.total_sentences,
            created_at=book.created_at,
            processed_at=book.processed_at,
            rights=RightsResponse.model_validate(rights, from_attributes=True),
            rights_problems=[p.value for p in rights_problems(rights_terms(rights), self._today())],
        )
