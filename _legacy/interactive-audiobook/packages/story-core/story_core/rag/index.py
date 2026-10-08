"""Builds the retrieval index for one book (worker task ``books.embed``).

Idempotent and cheap to re-run: chunks are content-addressed, so a second run over unchanged text embeds
nothing. Vectors are reused by ``(model_id, content_hash)`` *before* the old rows are replaced, which is
what keeps reprocessing a book (a typo fix, a better sentence splitter) from paying the provider again for
text that did not change.

Rights are re-checked here, not only in the API: embedding sends the book's text to a provider, and an
expired licence must stop that even if the job was enqueued while it was valid.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from story_core.books.rights import rights_problems, rights_today
from story_core.ingestion.pipeline import rights_terms
from story_core.models.book import Book, BookRights, BookStatus, Chapter, Paragraph, Sentence
from story_core.models.rag import EMBEDDING_DIMENSIONS, ParagraphEmbedding
from story_core.providers.embedding.base import EmbeddingProvider
from story_core.rag.chunking import Chunk, SourceParagraph, SourceSentence, build_chunks

logger = logging.getLogger(__name__)

_EMBED_BATCH = 32
_INSERT_BATCH = 500


@dataclass(frozen=True, slots=True)
class IndexOutcome:
    status: str
    chunks: int = 0
    embedded: int = 0
    reused: int = 0
    error: str | None = None


class ChunkIndexer:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        embedder: EmbeddingProvider,
        *,
        batch_size: int = _EMBED_BATCH,
        timeout_s: float = 30.0,
        today: Callable[[], date] = rights_today,
    ) -> None:
        if embedder.dimensions != EMBEDDING_DIMENSIONS:
            # PostgreSQL rejects the insert deep inside a batch with "expected N dimensions"; SQLite
            # accepts anything and the mismatch only shows up as unusable rows. Fail here instead.
            raise ValueError(
                f"embedding width {embedder.dimensions} != paragraph_embeddings column "
                f"{EMBEDDING_DIMENSIONS}; a different model needs its own table and a backfill"
            )
        self._sessionmaker = sessionmaker
        self._embedder = embedder
        self._batch_size = batch_size
        self._timeout_s = timeout_s
        self._today = today

    @property
    def model_id(self) -> str:
        return self._embedder.info.model

    async def index_book(self, book_id: uuid.UUID, *, expected_version: int | None = None) -> IndexOutcome:
        async with self._sessionmaker() as session:
            book = await session.get(Book, book_id)
            rights = await session.get(BookRights, book_id)
            if book is None:
                return IndexOutcome(status="missing")
            if book.status != BookStatus.READY:
                return IndexOutcome(status="skipped", error="book_not_ready")
            if expected_version is not None and book.processing_version != expected_version:
                logger.info("index_skipped_stale_job", extra={"book_id": str(book_id)})
                return IndexOutcome(status="skipped", error="stale_version")
            if rights is None or rights_problems(rights_terms(rights), self._today()):
                return IndexOutcome(status="failed", error="rights_insufficient")
            sources = await self._load_sources(session, book_id)

        chunks = build_chunks(sources)
        if not chunks:
            return IndexOutcome(status="empty")

        vectors, embedded, reused = await self._vectors_for(book_id, chunks)
        await self._replace(book_id, chunks, vectors)
        logger.info(
            "book_indexed",
            extra={
                "book_id": str(book_id),
                "chunks": len(chunks),
                "embedded": embedded,
                "reused": reused,
                "model": self.model_id,
            },
        )
        return IndexOutcome(status="ready", chunks=len(chunks), embedded=embedded, reused=reused)

    async def _load_sources(self, session: AsyncSession, book_id: uuid.UUID) -> list[SourceParagraph]:
        chapters = (
            await session.execute(select(Chapter.id, Chapter.title).where(Chapter.book_id == book_id))
        ).all()
        titles: dict[uuid.UUID, str] = {row.id: row.title for row in chapters}
        paragraphs = (
            await session.execute(
                select(
                    Paragraph.id,
                    Paragraph.chapter_id,
                    Paragraph.global_seq,
                    Paragraph.scene_break_before,
                )
                .where(Paragraph.book_id == book_id)
                .order_by(Paragraph.global_seq)
            )
        ).all()
        sentences = (
            await session.execute(
                select(Sentence.paragraph_id, Sentence.global_seq, Sentence.text)
                .where(Sentence.book_id == book_id)
                .order_by(Sentence.global_seq)
            )
        ).all()
        by_paragraph: dict[uuid.UUID, list[SourceSentence]] = {}
        for paragraph_id, global_seq, text in sentences:
            by_paragraph.setdefault(paragraph_id, []).append(SourceSentence(global_seq=global_seq, text=text))
        return [
            SourceParagraph(
                paragraph_id=row.id,
                chapter_id=row.chapter_id,
                chapter_title=titles.get(row.chapter_id, ""),
                global_seq=row.global_seq,
                scene_break_before=row.scene_break_before,
                sentences=by_paragraph.get(row.id, []),
            )
            for row in paragraphs
        ]

    async def _vectors_for(
        self, book_id: uuid.UUID, chunks: Sequence[Chunk]
    ) -> tuple[dict[str, list[float]], int, int]:
        hashes = {chunk.content_hash for chunk in chunks}
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(ParagraphEmbedding.content_hash, ParagraphEmbedding.embedding).where(
                        ParagraphEmbedding.book_id == book_id,
                        ParagraphEmbedding.model_id == self.model_id,
                        ParagraphEmbedding.content_hash.in_(hashes),
                    )
                )
            ).all()
        cached: dict[str, list[float]] = {row.content_hash: list(row.embedding) for row in rows}

        missing = [chunk for chunk in chunks if chunk.content_hash not in cached]
        # Deduplicate identical text inside one book (repeated refrains, chapter headings).
        pending: dict[str, str] = {chunk.content_hash: chunk.embed_text for chunk in missing}
        for start in range(0, len(pending), self._batch_size):
            batch = list(pending.items())[start : start + self._batch_size]
            result = await self._embedder.embed(
                [text for _, text in batch], kind="document", timeout_s=self._timeout_s
            )
            if len(result.vectors) != len(batch):
                raise RuntimeError("embedding provider returned the wrong number of vectors")
            for (content_hash, _), vector in zip(batch, result.vectors, strict=True):
                if len(vector) != self._embedder.dimensions:
                    raise RuntimeError("embedding provider returned the wrong width")
                cached[content_hash] = vector
        return cached, len(pending), len(chunks) - len(pending)

    async def _replace(
        self, book_id: uuid.UUID, chunks: Sequence[Chunk], vectors: dict[str, list[float]]
    ) -> None:
        rows = [
            {
                "id": uuid.uuid4(),
                "book_id": book_id,
                "paragraph_id": chunk.paragraph_id,
                "chapter_id": chunk.chapter_id,
                "chunk_index": chunk.chunk_index,
                "start_global_seq": chunk.start_global_seq,
                "end_global_seq": chunk.end_global_seq,
                "text": chunk.text,
                "content_hash": chunk.content_hash,
                "model_id": self.model_id,
                "embedding": vectors[chunk.content_hash],
            }
            for chunk in chunks
        ]
        async with self._sessionmaker() as session:
            # One transaction: a question must never see a half-rebuilt index.
            await session.execute(
                delete(ParagraphEmbedding).where(
                    ParagraphEmbedding.book_id == book_id,
                    ParagraphEmbedding.model_id == self.model_id,
                )
            )
            for start in range(0, len(rows), _INSERT_BATCH):
                await session.execute(insert(ParagraphEmbedding), rows[start : start + _INSERT_BATCH])
            await session.commit()
