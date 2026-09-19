"""Chunk search. Every path goes through one filtered base query.

The spoiler filter is not a caller's option: ``allowed_seq`` is a required argument and the
``end_global_seq <= allowed_seq`` clause is added by :func:`_allowed`, which every search below is built
on. FULL_SPOILER does not remove the clause — it passes a higher ``allowed_seq`` — so there is exactly one
code path and no "filter disabled" branch to get wrong (docs/ai-architecture.md §3.3).

Vector search is the one dialect-dependent part: PostgreSQL orders by the pgvector `<=>` operator with an
HNSW index; SQLite (fast local tests) scans the same filtered rows and computes cosine in Python, which is
also the documented exact-scan fallback for early reading positions where the filter is very selective.
"""

import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from story_core.models.book import Sentence
from story_core.models.rag import ParagraphEmbedding

CandidateSource = Literal["vector", "keyword", "window"]

# Korean function words and endings that carry no retrieval signal on their own.
_STOPWORDS = frozenset(
    """
    그리고 그러나 그래서 하지만 그런데 그러면 그리하여 때문에 대해 대한 위해 위한 있는 없는 이런 저런 그런
    무엇 누구 어디 언제 어떻게 왜 얼마 정말 진짜 아주 매우 너무 조금 다시 지금 이제 아직 벌써 계속 항상
    합니까 입니까 인가요 뭐야 뭔데 누가 어때 어떤 그거 이거 저거 거기 여기 저기 우리 너희 자기 자신
    """.split()
)
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: uuid.UUID
    paragraph_id: uuid.UUID
    chapter_id: uuid.UUID
    start_global_seq: int
    end_global_seq: int
    text: str
    # Higher is better. Comparable only within one source; ranks are what get fused.
    score: float
    source: CandidateSource


def query_terms(question: str, *, limit: int = 8) -> list[str]:
    """Content words for keyword search: longest first, so names outrank generic words."""
    seen: dict[str, None] = {}
    for token in _TOKEN.findall(question):
        if token in _STOPWORDS or len(token) < 2:
            continue
        seen.setdefault(token, None)
    ordered = sorted(seen, key=lambda term: (-len(term), term))
    return ordered[:limit]


_COLUMNS = (
    ParagraphEmbedding.id,
    ParagraphEmbedding.paragraph_id,
    ParagraphEmbedding.chapter_id,
    ParagraphEmbedding.start_global_seq,
    ParagraphEmbedding.end_global_seq,
    ParagraphEmbedding.text,
)


def _allowed(book_id: uuid.UUID, model_id: str, allowed_seq: int) -> Select[Any]:
    """The only way chunks are selected. No overload skips the spoiler clause."""
    return select(*_COLUMNS).where(
        ParagraphEmbedding.book_id == book_id,
        ParagraphEmbedding.model_id == model_id,
        ParagraphEmbedding.end_global_seq <= allowed_seq,
    )


def _candidate(row: Any, score: float, source: CandidateSource) -> Candidate:
    return Candidate(
        chunk_id=row.id,
        paragraph_id=row.paragraph_id,
        chapter_id=row.chapter_id,
        start_global_seq=row.start_global_seq,
        end_global_seq=row.end_global_seq,
        text=row.text,
        score=score,
        source=source,
    )


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class ChunkSearch:
    """Reads chunks for one book and one embedding model, never past ``allowed_seq``."""

    def __init__(self, session: AsyncSession, *, book_id: uuid.UUID, model_id: str) -> None:
        self._session = session
        self._book_id = book_id
        self._model_id = model_id

    @property
    def _is_postgresql(self) -> bool:
        bind = self._session.get_bind()
        return bind.dialect.name == "postgresql"

    async def window(self, *, allowed_seq: int, sentences_back: int, limit: int) -> list[Candidate]:
        """What the reader just heard. Always included, never searched for.

        The chunk being narrated *right now* usually extends past the current sentence, and dropping it
        for that reason would remove the most likely subject of the question ("그게 무슨 뜻이야?"). So a
        straddling chunk is included with its text cut to the sentences actually heard, and its
        ``end_global_seq`` reported as ``allowed_seq`` — the invariant holds, and no unheard sentence is
        ever shown.
        """
        low = max(allowed_seq - sentences_back, 0)
        statement = (
            select(*_COLUMNS)
            .where(
                ParagraphEmbedding.book_id == self._book_id,
                ParagraphEmbedding.model_id == self._model_id,
                # start (not end): the chunk in progress qualifies, and is truncated below.
                ParagraphEmbedding.start_global_seq <= allowed_seq,
                ParagraphEmbedding.end_global_seq >= low,
            )
            .order_by(ParagraphEmbedding.start_global_seq.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        straddling = [row for row in rows if row.end_global_seq > allowed_seq]
        heard = await self._heard_text(straddling, allowed_seq=allowed_seq)

        candidates: list[Candidate] = []
        for row in sorted(rows, key=lambda row: row.start_global_seq):
            text = row.text if row.end_global_seq <= allowed_seq else heard.get(row.id, "")
            if not text.strip():
                continue
            end = min(row.end_global_seq, allowed_seq)
            # Closer to the current position scores higher, so fusion prefers the nearest context.
            score = 1.0 / (1 + max(allowed_seq - end, 0))
            candidates.append(
                Candidate(
                    chunk_id=row.id,
                    paragraph_id=row.paragraph_id,
                    chapter_id=row.chapter_id,
                    start_global_seq=row.start_global_seq,
                    end_global_seq=end,
                    text=text,
                    score=score,
                    source="window",
                )
            )
        return candidates

    async def _heard_text(self, rows: Sequence[Any], *, allowed_seq: int) -> dict[uuid.UUID, str]:
        """Sentence-exact text for chunks the reader is in the middle of."""
        if not rows:
            return {}
        lowest = min(row.start_global_seq for row in rows)
        sentences = (
            await self._session.execute(
                select(Sentence.global_seq, Sentence.text)
                .where(
                    Sentence.book_id == self._book_id,
                    Sentence.global_seq >= lowest,
                    Sentence.global_seq <= allowed_seq,
                )
                .order_by(Sentence.global_seq)
            )
        ).all()
        by_seq = {row.global_seq: row.text for row in sentences}
        return {
            row.id: " ".join(
                by_seq[seq]
                for seq in range(row.start_global_seq, min(row.end_global_seq, allowed_seq) + 1)
                if seq in by_seq
            )
            for row in rows
        }

    async def vector(self, embedding: Sequence[float], *, allowed_seq: int, limit: int) -> list[Candidate]:
        if self._is_postgresql:
            return await self._vector_pgvector(embedding, allowed_seq=allowed_seq, limit=limit)
        return await self._vector_exact(embedding, allowed_seq=allowed_seq, limit=limit)

    async def _vector_pgvector(
        self, embedding: Sequence[float], *, allowed_seq: int, limit: int
    ) -> list[Candidate]:
        distance = ParagraphEmbedding.embedding.cosine_distance(list(embedding))
        statement = (
            _allowed(self._book_id, self._model_id, allowed_seq)
            .add_columns(distance.label("distance"))
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [_candidate(row, 1.0 - float(row.distance), "vector") for row in rows]

    async def _vector_exact(
        self, embedding: Sequence[float], *, allowed_seq: int, limit: int
    ) -> list[Candidate]:
        statement = _allowed(self._book_id, self._model_id, allowed_seq).add_columns(
            ParagraphEmbedding.embedding
        )
        rows = (await self._session.execute(statement)).all()
        scored = [(_candidate(row, cosine_similarity(embedding, row.embedding), "vector")) for row in rows]
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        return scored[:limit]

    async def keyword(self, terms: Sequence[str], *, allowed_seq: int, limit: int) -> list[Candidate]:
        """Term containment, weighted by term length.

        Names and places are what users ask about, and PostgreSQL has no Korean morphology, so this is
        substring matching accelerated by a trigram GIN index (the same index makes ``LIKE '%x%'``
        indexable). BM25 over analysed tokens is the documented upgrade path.
        """
        if not terms:
            return []
        weights: list[ColumnElement[Any]] = [
            case((ParagraphEmbedding.text.contains(term), literal(float(len(term)))), else_=literal(0.0))
            for term in terms
        ]
        score = sum(weights[1:], weights[0]).label("score")
        statement = (
            _allowed(self._book_id, self._model_id, allowed_seq)
            .add_columns(score)
            .where(score > 0)
            .order_by(score.desc(), ParagraphEmbedding.end_global_seq.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [_candidate(row, float(row.score), "keyword") for row in rows]
