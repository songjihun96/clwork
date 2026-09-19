"""Retriever: question + reading position → the chunks an answer may use.

Order of business (docs/ai-architecture.md §3.2): the position window is always included without being
searched for — what the reader just heard is the most likely subject of "그게 무슨 뜻이야?" — then vector and
keyword candidates are fused by rank. A second ``end_global_seq`` check runs over the merged list: the SQL
filter is the real defence, but a bug that ever got past it would leak the ending, so it is cheap to
verify and loud when it fails.
"""

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from story_core.providers.base import Usage
from story_core.providers.embedding.base import EmbeddingProvider
from story_core.rag.fusion import reciprocal_rank_fusion
from story_core.rag.search import Candidate, ChunkSearch, query_terms

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    # Question embedding is on the answer's critical path, so it gets a tighter budget than indexing.
    embed_timeout_s: float = 5.0
    vector_k: int = 8
    keyword_k: int = 8
    # How much of the just-heard text to keep, in sentences and in chunks.
    window_sentences: int = 12
    window_chunks: int = 3
    final_k: int = 6
    # Cosine similarity below this is noise; with a lexical fake embedder almost everything scores low,
    # so the threshold applies to vector candidates only and never removes window chunks.
    min_vector_score: float = 0.12
    weights: tuple[tuple[str, float], ...] = (("window", 1.3), ("vector", 1.0), ("keyword", 0.8))


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    paragraph_id: uuid.UUID
    start_global_seq: int
    end_global_seq: int
    text: str
    sources: tuple[str, ...]
    score: float


@dataclass(frozen=True, slots=True)
class Retrieval:
    chunks: list[RetrievedChunk]
    allowed_seq: int
    usage: Usage = field(default_factory=Usage)
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def grounded(self) -> bool:
        return bool(self.chunks)


class Retriever:
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingProvider,
        *,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._config = config or RetrievalConfig()

    async def retrieve(self, question: str, *, book_id: uuid.UUID, allowed_seq: int) -> Retrieval:
        config = self._config
        search = ChunkSearch(self._session, book_id=book_id, model_id=self._embedder.info.model)
        timings: dict[str, int] = {}

        started = time.perf_counter()
        embedded = await self._embedder.embed([question], kind="query", timeout_s=config.embed_timeout_s)
        timings["embed"] = _elapsed_ms(started)
        vector_query = embedded.vectors[0] if embedded.vectors else []

        started = time.perf_counter()
        window = await search.window(
            allowed_seq=allowed_seq,
            sentences_back=config.window_sentences,
            limit=config.window_chunks,
        )
        vector = (
            await search.vector(vector_query, allowed_seq=allowed_seq, limit=config.vector_k)
            if vector_query
            else []
        )
        vector = [candidate for candidate in vector if candidate.score >= config.min_vector_score]
        keyword = await search.keyword(query_terms(question), allowed_seq=allowed_seq, limit=config.keyword_k)
        timings["search"] = _elapsed_ms(started)

        chunks = self._merge(window, vector, keyword, allowed_seq=allowed_seq)
        return Retrieval(chunks=chunks, allowed_seq=allowed_seq, usage=embedded.usage, timings_ms=timings)

    def _merge(
        self,
        window: Sequence[Candidate],
        vector: Sequence[Candidate],
        keyword: Sequence[Candidate],
        *,
        allowed_seq: int,
    ) -> list[RetrievedChunk]:
        by_id: dict[uuid.UUID, Candidate] = {}
        sources: dict[uuid.UUID, list[str]] = {}
        for candidates in (window, vector, keyword):
            for candidate in candidates:
                by_id.setdefault(candidate.chunk_id, candidate)
                sources.setdefault(candidate.chunk_id, []).append(candidate.source)

        fused = reciprocal_rank_fusion(
            {
                "window": [c.chunk_id for c in window],
                "vector": [c.chunk_id for c in vector],
                "keyword": [c.chunk_id for c in keyword],
            },
            weights=dict(self._config.weights),
        )
        window_ids = [c.chunk_id for c in window]
        scores = {item.key: item.score for item in fused}
        # Window chunks are kept unconditionally; the rest compete for the remaining slots.
        ordered = window_ids + [item.key for item in fused if item.key not in set(window_ids)]
        selected = ordered[: max(self._config.final_k, len(window_ids))]

        chunks: list[RetrievedChunk] = []
        for chunk_id in selected:
            candidate = by_id[chunk_id]
            if candidate.end_global_seq > allowed_seq:  # unreachable unless the SQL filter regressed
                logger.error(
                    "retrieval_spoiler_filter_violation",
                    extra={"chunk_end_seq": candidate.end_global_seq, "allowed_seq": allowed_seq},
                )
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    paragraph_id=candidate.paragraph_id,
                    start_global_seq=candidate.start_global_seq,
                    end_global_seq=candidate.end_global_seq,
                    text=candidate.text,
                    sources=tuple(dict.fromkeys(sources[chunk_id])),
                    score=scores.get(chunk_id, 0.0),
                )
            )
        # Nearest to the reading position first: the answer should lead with what just happened.
        chunks.sort(key=lambda chunk: (-_is_window(chunk), -chunk.score))
        return chunks


def _is_window(chunk: RetrievedChunk) -> int:
    return 1 if "window" in chunk.sources else 0


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
