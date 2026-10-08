"""Evaluate retrieval, the spoiler defence and refusal behaviour against a gold set.

    python scripts/eval_rag.py [--gold ../../infrastructure/eval/rag_gold_moonlight.json] [--verbose]

Runs the real pipeline (ingest → chunk → embed → retrieve → answer) over a throwaway database, one
question at a time, with the reading position moved to where each question is asked. Three numbers come
out, and only the middle one is a hard gate:

* **retrieval hit rate** — did a chunk containing the answer reach the model? Judge it together with the
  printed selectivity: retrieving most of a short book would score 100% while measuring nothing, so the
  run uses a deliberately tight top-k. With the offline lexical embedder this covers the keyword path and
  the plumbing; paraphrase recall needs the real embedding model.
* **spoiler leaks** — must be 0. A leak is later text appearing in the context *or* in the answer.
* **refusal rate on unanswerable questions** — only meaningful with a real LLM. The stub provider answers
  from whatever context it is given by construction, so it scores 0% by design; run with
  ``--llm openai_compatible`` once an endpoint is configured to get the real number.

Exit code is non-zero if any spoiler leaked, so this can gate a release.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from story_core.db.session import DatabaseOptions, create_engine, create_sessionmaker
from story_core.ingestion.pipeline import ingest_book
from story_core.models import (
    Base,
    Book,
    BookRights,
    BookStatus,
    ParagraphEmbedding,
    ReadingPosition,
    ReadingSession,
    Sentence,
    SourceFormat,
    User,
)
from story_core.providers.embedding.fake import FakeEmbeddingProvider
from story_core.providers.llm.fake import FakeLLMProvider
from story_core.providers.registry import LLMConfig, build_resilient_llm
from story_core.rag.answering import QuestionService
from story_core.rag.index import ChunkIndexer
from story_core.rag.retrieval import RetrievalConfig, Retriever
from story_core.rag.spoiler import SAFE_ANSWER
from story_core.reading.sessions import ReadingSessionService
from story_core.storage.local import LocalFileStorage

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLD = REPO_ROOT / "infrastructure" / "eval" / "rag_gold_moonlight.json"
# Phrases that count as "I don't know" for the refusal metric.
REFUSAL_MARKERS = ("찾지 못", "모르", "알 수 없", "나오지 않", SAFE_ANSWER)


@dataclass
class Result:
    item_id: str
    kind: str
    allowed_seq: int
    chunks: int
    reachable: int = 0
    hit: bool | None = None
    leaked: list[str] = field(default_factory=list)
    refused: bool | None = None
    answer: str = ""


def is_refusal(answer: str) -> bool:
    return any(marker in answer for marker in REFUSAL_MARKERS)


async def seq_of(session: AsyncSession, book_id: uuid.UUID, needle: str) -> int:
    seq = await session.scalar(
        select(Sentence.global_seq)
        .where(Sentence.book_id == book_id, Sentence.text.contains(needle))
        .order_by(Sentence.global_seq)
        .limit(1)
    )
    if seq is None:
        raise SystemExit(f"gold set refers to text that is not in the book: {needle!r}")
    return int(seq)


async def prepare(
    sessionmaker: async_sessionmaker[AsyncSession], storage: LocalFileStorage, source: bytes, title: str
) -> uuid.UUID:
    book_id = uuid.uuid4()
    digest = hashlib.sha256(source).hexdigest()
    key = f"books/{book_id}/source/{digest}.txt"
    await storage.put_bytes(key, source, content_type="text/plain")
    async with sessionmaker() as session:
        session.add(
            Book(
                id=book_id,
                title=title,
                status=BookStatus.QUEUED,
                source_format=SourceFormat.TXT,
                source_storage_key=key,
                source_sha256=digest,
                source_byte_size=len(source),
            )
        )
        await session.flush()
        session.add(
            BookRights(
                book_id=book_id,
                rights_type="owned",
                rights_holder="Interactive Audiobook project",
                commercial_use=True,
                audio_rights=True,
                ai_processing_rights=True,
                contract_ref="original-eval-text",
            )
        )
        await session.commit()
    outcome = await ingest_book(sessionmaker, storage, book_id)
    if outcome.status != BookStatus.READY:
        raise SystemExit(f"ingestion failed: {outcome}")
    return book_id


async def move_to(sessionmaker: async_sessionmaker[AsyncSession], session_id: uuid.UUID, seq: int) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(ReadingPosition)
            .where(ReadingPosition.session_id == session_id)
            .values(sentence_global_seq=seq)
        )
        # Set (not raise) max_read_seq: the eval walks backwards as well as forwards.
        await session.execute(
            update(ReadingSession).where(ReadingSession.id == session_id).values(max_read_seq=seq)
        )
        await session.commit()


async def run(
    gold: dict[str, Any], source: bytes, *, verbose: bool, config: RetrievalConfig, llm_name: str
) -> int:

    with TemporaryDirectory(prefix="rag-eval-") as tmp:
        root = Path(tmp)
        engine = create_engine(
            DatabaseOptions(url=f"sqlite+aiosqlite:///{root / 'eval.db'}", application_name="rag-eval")
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessionmaker = create_sessionmaker(engine)
        storage = LocalFileStorage(root / "storage")
        embedder = FakeEmbeddingProvider(dimensions=1024)

        book_id = await prepare(sessionmaker, storage, source, gold.get("title", "eval"))
        indexed = await ChunkIndexer(sessionmaker, embedder).index_book(book_id)
        print(f"book={book_id} chunks={indexed.chunks} embedded={indexed.embedded}")

        user_id = uuid.uuid4()
        async with sessionmaker() as session:
            session.add(User(id=user_id, email=f"eval-{user_id.hex[:8]}@example.com"))
            await session.commit()
        async with sessionmaker() as session:
            view, _ = await ReadingSessionService(session).open(user_id, book_id)
            session_id = view.session.id

        llm = build_llm(llm_name)
        print(f"llm={llm.info.provider}:{llm.info.model} retrieval final_k={config.final_k}")
        results: list[Result] = []
        for item in gold["items"]:
            async with sessionmaker() as session:
                allowed = await seq_of(session, book_id, item["ask_after"])
            await move_to(sessionmaker, session_id, allowed)

            async with sessionmaker() as session:
                reading = ReadingSessionService(session)
                view = await reading.get(user_id, session_id)
                retriever = Retriever(session, embedder, config=config)
                service = QuestionService(session, retriever=retriever, llm=llm)
                answer = await service.ask(view, item["question"])
                retrieval = await retriever.retrieve(
                    item["question"], book_id=book_id, allowed_seq=answer.allowed_seq
                )
                context = "\n".join(chunk.text for chunk in retrieval.chunks)
                reachable = await count_reachable(session, book_id, answer.allowed_seq)

            result = Result(
                item_id=item["id"],
                kind=item["kind"],
                allowed_seq=answer.allowed_seq,
                chunks=len(answer.citations),
                reachable=reachable,
                answer=answer.text,
            )
            if item["kind"] == "grounded":
                result.hit = any(needle in context for needle in item["evidence"])
            elif item["kind"] == "future":
                haystack = f"{context}\n{answer.text}"
                result.leaked = [needle for needle in item["forbidden"] if needle in haystack]
            else:
                result.refused = is_refusal(answer.text)
            results.append(result)
            if verbose:
                mark = "leak" if result.leaked else ("hit" if result.hit else "")
                print(f"  {result.item_id:4} seq={result.allowed_seq:3} {mark:4} {result.answer[:60]}")

        await engine.dispose()

    grounded = [r for r in results if r.kind == "grounded"]
    future = [r for r in results if r.kind == "future"]
    ungrounded = [r for r in results if r.kind == "ungrounded"]
    hits = sum(1 for r in grounded if r.hit)
    leaks = [r for r in future if r.leaked]
    refusals = sum(1 for r in ungrounded if r.refused)

    print(
        f"\nitems: {len(results)} (grounded {len(grounded)}, "
        f"future {len(future)}, unanswerable {len(ungrounded)})"
    )
    selectivity = [r.chunks / r.reachable for r in grounded if r.reachable]
    share = sum(selectivity) / len(selectivity) if selectivity else 0.0
    print(f"retrieval hit rate : {hits}/{len(grounded)} ({hits / max(len(grounded), 1):.0%})")
    print(f"  selectivity      : {share:.0%} of the chunks the reader may see were sent to the model")
    print(f"spoiler leaks      : {len(leaks)}/{len(future)}  (hard gate)")
    print(f"refusal rate       : {refusals}/{len(ungrounded)} ({refusals / max(len(ungrounded), 1):.0%})")
    if llm_name == "fake":
        print("  refusal rate is not meaningful with the stub LLM; rerun with --llm openai_compatible")
    if leaks:
        for leak in leaks:
            print(f"  LEAK {leak.item_id}: {leak.leaked} at allowed_seq={leak.allowed_seq}")
    misses = [r.item_id for r in grounded if not r.hit]
    if misses:
        print(f"retrieval misses   : {', '.join(misses)}")
    return 1 if leaks else 0


def build_llm(name: str) -> object:
    """The stub by default; a real endpoint when one is configured through the environment."""
    if name == "fake":
        return FakeLLMProvider()
    return build_resilient_llm(
        LLMConfig(
            provider=name,
            model=os.environ.get("LLM_MODEL", ""),
            base_url=os.environ.get("LLM_BASE_URL"),
            api_key=os.environ.get("LLM_API_KEY"),
        )
    )


async def count_reachable(session: AsyncSession, book_id: uuid.UUID, allowed_seq: int) -> int:
    """Chunks the spoiler filter allows — the denominator for selectivity."""
    total = await session.scalar(
        select(func.count())
        .select_from(ParagraphEmbedding)
        .where(ParagraphEmbedding.book_id == book_id, ParagraphEmbedding.end_global_seq <= allowed_seq)
    )
    return int(total or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--llm", default="fake", choices=["fake", "openai_compatible"])
    parser.add_argument("--final-k", type=int, default=3)
    parser.add_argument("--window-chunks", type=int, default=1)
    args = parser.parse_args()
    config = RetrievalConfig(final_k=args.final_k, window_chunks=args.window_chunks)
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    source = (REPO_ROOT / gold["book"]).read_bytes()
    return asyncio.run(run(gold, source, verbose=args.verbose, config=config, llm_name=args.llm))


if __name__ == "__main__":
    raise SystemExit(main())
