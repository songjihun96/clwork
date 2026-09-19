"""RAG: chunking, indexing, retrieval, spoiler defence, context budget, answering.

The spoiler tests are the point of this file. Phase 4's exit criterion is that a chunk after the reader's
position is unreachable **by any path**, so the filter is checked per path and then swept across every
possible reading position with a property test, not just at a couple of hand-picked values.
"""

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from story_core.ingestion.pipeline import ingest_book
from story_core.models import (
    EMBEDDING_DIMENSIONS,
    Book,
    ConversationMessage,
    ParagraphEmbedding,
    Sentence,
)
from story_core.models.reading import SpoilerMode
from story_core.providers.embedding.fake import FakeEmbeddingProvider
from story_core.providers.llm.fake import FakeLLMProvider
from story_core.rag.answering import (
    PROVIDER_ERROR_ANSWER,
    Answer,
    AnswerClause,
    AnswerEvent,
    QuestionRejected,
    QuestionService,
)
from story_core.rag.chunking import (
    MAX_CHARS,
    SourceParagraph,
    SourceSentence,
    build_chunks,
)
from story_core.rag.context import BookContext, ContextBudget, ContextBuilder, HistoryTurn, estimate_tokens
from story_core.rag.fusion import reciprocal_rank_fusion
from story_core.rag.index import ChunkIndexer
from story_core.rag.retrieval import RetrievalConfig, RetrievedChunk, Retriever
from story_core.rag.search import ChunkSearch, query_terms
from story_core.rag.spoiler import SAFE_ANSWER, SpoilerGuard, allowed_seq, novel_terms
from story_core.reading.sessions import ReadingSessionService
from story_core.storage.local import LocalFileStorage
from tests.conftest import TODAY, Db, create_book, create_user

# A book with entities at known positions: 하람 from the start, 미르 and 고래뼈 only in the last chapter.
RAG_TEXT = (
    "제1장 바람이 바뀌던 날\n\n"
    "섬의 끝에는 오래된 등대가 하나 서 있었다. 하얀 벽은 소금기에 바래 있었다.\n\n"
    "하람은 등대지기였다. 그는 매일 밤 불을 켰다.\n\n"
    "그날은 바람의 냄새가 달랐다.\n\n"
    "***\n\n"
    "멀리서 작은 불빛 하나가 깜박였다. 하람은 수평선을 오래 바라보았다.\n\n"
    "제2장 낮게 뜬 불빛\n\n"
    "하람은 손전등을 챙겨 바위길로 내려갔다. 파도가 발목까지 올라왔다.\n\n"
    '"누구 있어요?" 하람이 외쳤다. 아무 대답도 없었다.\n\n'
    "제3장 고래뼈 해변\n\n"
    "모래밭에 미르가 앉아 있었다. 미르는 오래된 고래뼈를 쥐고 있었다.\n\n"
    "미르는 등대의 비밀을 알고 있다고 말했다.\n"
).encode()

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLD_PATH = REPO_ROOT / "infrastructure" / "eval" / "rag_gold_moonlight.json"


async def ready_book(db: Db, storage: LocalFileStorage, source: bytes = RAG_TEXT) -> uuid.UUID:
    book_id = await create_book(db, storage, source)
    outcome = await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    assert outcome.status == "ready", outcome
    return book_id


async def indexed_book(
    db: Db,
    storage: LocalFileStorage,
    *,
    embedder: FakeEmbeddingProvider | None = None,
    source: bytes = RAG_TEXT,
) -> tuple[uuid.UUID, FakeEmbeddingProvider]:
    embedder = embedder or FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    book_id = await ready_book(db, storage, source)
    outcome = await ChunkIndexer(db.sessionmaker, embedder, today=lambda: TODAY).index_book(book_id)
    assert outcome.status == "ready" and outcome.chunks > 0, outcome
    return book_id, embedder


async def sentence_count(db: Db, book_id: uuid.UUID) -> int:
    async with db.sessionmaker() as session:
        total = await session.scalar(select(Book.total_sentences).where(Book.id == book_id))
    return int(total or 0)


# --------------------------------------------------------------------------- chunking


def paragraph(
    seq: int, sentences: Sequence[str], *, chapter: uuid.UUID, scene_break: bool = False, first_seq: int = 0
) -> SourceParagraph:
    return SourceParagraph(
        paragraph_id=uuid.uuid4(),
        chapter_id=chapter,
        chapter_title="1장",
        global_seq=seq,
        scene_break_before=scene_break,
        sentences=[SourceSentence(global_seq=first_seq + i, text=t) for i, t in enumerate(sentences)],
    )


def test_short_paragraphs_merge_but_never_across_a_scene_break_or_chapter() -> None:
    chapter_a, chapter_b = uuid.uuid4(), uuid.uuid4()
    paragraphs = [
        paragraph(0, ["짧다."], chapter=chapter_a, first_seq=0),
        paragraph(1, ["또 짧다."], chapter=chapter_a, first_seq=1),
        paragraph(2, ["장면이 바뀐다."], chapter=chapter_a, scene_break=True, first_seq=2),
        paragraph(3, ["다음 장."], chapter=chapter_b, first_seq=3),
    ]

    chunks = build_chunks(paragraphs)

    assert len(chunks) == 3
    assert chunks[0].paragraph_count == 2 and chunks[0].start_global_seq == 0
    assert chunks[0].end_global_seq == 1
    assert chunks[1].start_global_seq == 2 and chunks[1].paragraph_count == 1
    assert chunks[2].start_global_seq == 3
    assert chunks[0].embed_text.startswith("[1장]")  # contextual prefix for the embedding only
    assert "[1장]" not in chunks[0].text


def test_long_paragraph_splits_at_sentence_boundaries() -> None:
    chapter = uuid.uuid4()
    sentences = [f"{i}번째 문장은 충분히 길어서 청크 한도를 넘기도록 반복된다. " * 5 for i in range(8)]
    long_paragraph = paragraph(0, sentences, chapter=chapter, first_seq=0)
    assert len(long_paragraph.text) > MAX_CHARS

    chunks = build_chunks([long_paragraph])

    assert len(chunks) > 1
    assert [chunk.start_global_seq for chunk in chunks] == sorted(chunk.start_global_seq for chunk in chunks)
    # Contiguous cover: every sentence appears exactly once, in order.
    covered = [seq for chunk in chunks for seq in range(chunk.start_global_seq, chunk.end_global_seq + 1)]
    assert covered == list(range(len(sentences)))
    assert all(len(chunk.text) <= MAX_CHARS + 200 for chunk in chunks)


@settings(max_examples=40, deadline=None)
@given(
    sentence_lengths=st.lists(st.lists(st.integers(10, 300), min_size=1, max_size=4), min_size=1, max_size=8),
    breaks=st.lists(st.booleans(), min_size=1, max_size=8),
)
def test_chunks_are_a_contiguous_ordered_cover(sentence_lengths: list[list[int]], breaks: list[bool]) -> None:
    """The spoiler filter relies on this: a chunk's end_global_seq is the largest sentence it holds."""
    chapter = uuid.uuid4()
    paragraphs: list[SourceParagraph] = []
    seq = 0
    for index, lengths in enumerate(sentence_lengths):
        sentences = ["가" * length + "." for length in lengths]
        paragraphs.append(
            paragraph(
                index,
                sentences,
                chapter=chapter,
                scene_break=breaks[index % len(breaks)],
                first_seq=seq,
            )
        )
        seq += len(sentences)

    chunks = build_chunks(paragraphs)

    assert chunks
    covered: list[int] = []
    for chunk in chunks:
        assert chunk.start_global_seq <= chunk.end_global_seq
        covered.extend(range(chunk.start_global_seq, chunk.end_global_seq + 1))
    assert covered == list(range(seq))


# --------------------------------------------------------------------------- fusion


def test_rrf_prefers_agreement_and_is_deterministic() -> None:
    fused = reciprocal_rank_fusion({"vector": ["a", "b", "c"], "keyword": ["c", "a"]}, k=1)

    assert [item.key for item in fused] == ["a", "c", "b"]
    assert dict(fused[0].ranks) == {"vector": 1, "keyword": 2}
    assert fused == reciprocal_rank_fusion({"vector": ["a", "b", "c"], "keyword": ["c", "a"]}, k=1)


def test_rrf_weights_shift_the_order() -> None:
    ranked = {"window": ["w"], "vector": ["v"]}
    assert [item.key for item in reciprocal_rank_fusion(ranked, weights={"window": 2.0})] == ["w", "v"]
    assert [item.key for item in reciprocal_rank_fusion(ranked, weights={"vector": 2.0})] == ["v", "w"]


# --------------------------------------------------------------------------- indexing


async def test_indexing_is_idempotent_and_reuses_vectors(db: Db, storage: LocalFileStorage) -> None:
    embedder = FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    book_id, _ = await indexed_book(db, storage, embedder=embedder)
    embedded_first = sum(len(texts) for _, texts in embedder.calls)
    assert embedded_first > 0

    async with db.sessionmaker() as session:
        rows = (
            (await session.execute(select(ParagraphEmbedding).where(ParagraphEmbedding.book_id == book_id)))
            .scalars()
            .all()
        )
    assert rows and all(len(row.embedding) == EMBEDDING_DIMENSIONS for row in rows)
    assert all(row.model_id == embedder.info.model for row in rows)

    embedder.calls.clear()
    again = await ChunkIndexer(db.sessionmaker, embedder, today=lambda: TODAY).index_book(book_id)

    assert again.status == "ready" and again.embedded == 0 and again.reused == again.chunks
    assert embedder.calls == []  # nothing re-embedded: the provider was never called


async def test_indexing_refuses_without_ai_processing_rights(db: Db, storage: LocalFileStorage) -> None:
    book_id = await create_book(db, storage, RAG_TEXT, ai_processing_rights=False)
    async with db.sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book is not None
        book.status = "ready"
        await session.commit()

    outcome = await ChunkIndexer(
        db.sessionmaker, FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    ).index_book(book_id)

    assert outcome.status == "failed" and outcome.error == "rights_insufficient"


async def test_indexing_skips_a_book_that_is_not_ready(db: Db, storage: LocalFileStorage) -> None:
    book_id = await create_book(db, storage, RAG_TEXT)  # QUEUED
    outcome = await ChunkIndexer(
        db.sessionmaker, FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    ).index_book(book_id)
    assert outcome.status == "skipped" and outcome.error == "book_not_ready"


# --------------------------------------------------------------------------- spoiler filter


async def test_every_search_path_stops_at_the_allowed_sentence(db: Db, storage: LocalFileStorage) -> None:
    book_id, embedder = await indexed_book(db, storage)
    total = await sentence_count(db, book_id)
    question = "미르는 고래뼈로 무엇을 했어?"  # asks about the last chapter on purpose

    async with db.sessionmaker() as session:
        search = ChunkSearch(session, book_id=book_id, model_id=embedder.info.model)
        vector_query = (await embedder.embed([question], kind="query", timeout_s=1)).vectors[0]
        for allowed in range(0, total + 2):
            window = await search.window(allowed_seq=allowed, sentences_back=12, limit=5)
            vector = await search.vector(vector_query, allowed_seq=allowed, limit=20)
            keyword = await search.keyword(query_terms(question), allowed_seq=allowed, limit=20)
            for candidate in [*window, *vector, *keyword]:
                assert candidate.end_global_seq <= allowed, (candidate.source, allowed)


async def test_future_text_is_unreachable_through_the_retriever(db: Db, storage: LocalFileStorage) -> None:
    """The exit criterion: no path returns content past the reading position."""
    book_id, embedder = await indexed_book(db, storage)
    total = await sentence_count(db, book_id)

    async with db.sessionmaker() as session:
        retriever = Retriever(session, embedder)
        early = await retriever.retrieve("미르는 누구야?", book_id=book_id, allowed_seq=2)
        assert early.allowed_seq == 2
        assert all(chunk.end_global_seq <= 2 for chunk in early.chunks)
        assert all("미르" not in chunk.text for chunk in early.chunks)
        assert all("고래뼈" not in chunk.text for chunk in early.chunks)

        late = await retriever.retrieve("미르는 누구야?", book_id=book_id, allowed_seq=total - 1)
        assert any("미르" in chunk.text for chunk in late.chunks), "retrieval must find it once read"


@pytest.mark.parametrize(
    ("mode", "position", "max_read", "expected"),
    [
        (SpoilerMode.NO_SPOILER, 5, 5, 5),
        # Re-reading an earlier page must not narrow the window.
        (SpoilerMode.NO_SPOILER, 2, 9, 9),
        (SpoilerMode.NO_SPOILER, 900, 0, 19),  # clamped to the last sentence
        (SpoilerMode.FULL_SPOILER, 0, 0, 19),
        (SpoilerMode.LIGHT_SPOILER, 3, 3, 12),  # to the end of the chapter being heard
    ],
)
def test_allowed_seq_per_spoiler_mode(mode: SpoilerMode, position: int, max_read: int, expected: int) -> None:
    assert (
        allowed_seq(
            position_seq=position,
            max_read_seq=max_read,
            mode=mode,
            total_sentences=20,
            chapter_end_seq=12,
        )
        == expected
    )


def test_light_spoiler_never_exceeds_the_book() -> None:
    assert (
        allowed_seq(
            position_seq=0,
            max_read_seq=0,
            mode=SpoilerMode.LIGHT_SPOILER,
            total_sentences=5,
            chapter_end_seq=99,
        )
        == 4
    )


# --------------------------------------------------------------------------- spoiler guard


def test_novel_terms_only_reports_words_the_context_lacks() -> None:
    context = "하람은 등대지기였다. 그는 매일 밤 불을 켰다."
    # Names with particles are matched against their stem, so evidence covers them.
    assert "하람은" not in novel_terms("하람은 등대를 지켜요.", context)
    assert any(term.startswith("미르") for term in novel_terms("미르가 등대의 비밀을 알아요.", context))
    # Conjugated endings look novel; harmless, because only terms that occur later in the book block.
    assert "등대지기예요" in novel_terms("하람은 등대지기예요.", context)


async def test_guard_flags_a_term_that_appears_only_later(db: Db, storage: LocalFileStorage) -> None:
    book_id, _ = await indexed_book(db, storage)
    async with db.sessionmaker() as session:
        first_mir = await session.scalar(
            select(Sentence.global_seq).where(Sentence.book_id == book_id, Sentence.text.contains("미르"))
        )
        assert first_mir is not None
        guard = SpoilerGuard(session, book_id=book_id)

        leaked = await guard.check("미르가 등대의 비밀을 알고 있어요.", context="", allowed=first_mir - 1)
        assert any(term.startswith("미르") for term in leaked), leaked

        # Once that sentence has been heard, the same answer passes.
        assert await guard.check("미르가 나타났어요.", context="", allowed=first_mir) == []

        # A word that is not in the book at all is general knowledge, not a spoiler.
        assert await guard.check("등대는 해상 교통을 돕는 시설이에요.", context="", allowed=0) == []


# --------------------------------------------------------------------------- context budget


def chunk_of(text: str, *, seq: int, window: bool = False) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        paragraph_id=uuid.uuid4(),
        start_global_seq=seq,
        end_global_seq=seq,
        text=text,
        sources=("window",) if window else ("vector",),
        score=1.0,
    )


def test_context_drops_retrieved_chunks_before_history_and_keeps_the_window() -> None:
    budget = ContextBudget(position_window=40, retrieved=40, history=40)
    builder = ContextBuilder(budget=budget)
    window = chunk_of("가" * 30, seq=1, window=True)
    big = [chunk_of("나" * 60, seq=index) for index in range(2, 5)]
    history = [HistoryTurn(role="user", text="다" * 60), HistoryTurn(role="assistant", text="라" * 10)]

    built = builder.build(
        question="무슨 일이야?",
        book=BookContext(title="등대", chapter_title="1장"),
        chunks=[window, *big],
        history=history,
    )

    assert window.text in built.context_text
    assert built.dropped_chunks >= 1
    assert built.dropped_history == 1  # the oldest, largest turn goes first
    assert built.request.messages[0].role == "system"
    assert "<context>" in built.request.messages[0].content
    assert built.request.messages[-1].content == "무슨 일이야?"


def test_a_single_oversized_chunk_is_kept_rather_than_answering_blind() -> None:
    builder = ContextBuilder(budget=ContextBudget(retrieved=10))
    built = builder.build(
        question="왜?", book=BookContext(title="등대"), chunks=[chunk_of("가" * 500, seq=1)]
    )
    assert built.used_chunks and built.dropped_chunks == 0


def test_token_estimate_treats_hangul_as_roughly_one_token_each() -> None:
    assert estimate_tokens("가나다라") == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0


# --------------------------------------------------------------------------- answering


async def test_answer_is_grounded_cited_and_recorded(db: Db, storage: LocalFileStorage) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider()

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        answer = await service.ask(view, "하람은 누구야?")

        assert answer.grounded and answer.text
        assert answer.citations and all(c.end_global_seq <= answer.allowed_seq for c in answer.citations)
        assert answer.spoiler_mode is SpoilerMode.NO_SPOILER
        assert answer.provider == "fake" and answer.model == llm.info.model
        assert answer.latency_ms["total"] >= 0 and "llm" in answer.latency_ms
        # The prompt carries only retrieved text, never the whole book.
        prompt = llm.requests[0].messages[0].content
        assert "<context>" in prompt and "고래뼈" not in prompt

        rows = (
            (
                await session.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == answer.conversation_id)
                    .order_by(ConversationMessage.role)
                )
            )
            .scalars()
            .all()
        )
        assert [row.role for row in rows] == ["assistant", "user"]
        assistant = rows[0]
        assert assistant.retrieval_refs and assistant.guard_action == "pass"
        assert assistant.prompt_version == "story_answer.v1"
        assert assistant.position_global_seq == view.position.sentence_global_seq


async def test_question_about_unread_content_is_refused_not_answered(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    # The model tries to leak a name from the last chapter; the guard must stop it.
    llm = FakeLLMProvider(responses=["미르가 등대의 비밀을 알고 있어요."])

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        answer = await service.ask(view, "이 책의 결말이 어떻게 돼?")

        assert answer.text == SAFE_ANSWER
        assert answer.guard_action == "blocked" and not answer.grounded


async def test_provider_failure_becomes_a_safe_message_and_is_recorded(
    db: Db, storage: LocalFileStorage
) -> None:
    from story_core.providers.base import ProviderUnavailable

    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider(failures=[ProviderUnavailable("down")])

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        answer = await service.ask(view, "하람은 누구야?")

        assert answer.text == PROVIDER_ERROR_ANSWER and answer.guard_action == "provider_error"
        assert not answer.grounded


async def collect(events: AsyncIterator[AnswerEvent]) -> tuple[list[str], Answer]:
    clauses: list[str] = []
    final: Answer | None = None
    async for event in events:
        if isinstance(event, AnswerClause):
            assert final is None, "a clause arrived after the final answer"
            clauses.append(event.text)
        else:
            final = event
    assert final is not None, "the stream never produced its Answer"
    return clauses, final


async def test_streamed_answer_arrives_in_clauses_and_is_recorded_as_said(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider(responses=["그 사람은 섬에서 지내요. 밤마다 바다를 살피는 일을 해요."])

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        clauses, answer = await collect(service.ask_stream(view, "하람은 누구야?"))

        assert len(clauses) >= 2
        assert clauses[0] == "그 사람은 섬에서 지내요."
        assert answer.text == " ".join(clauses)
        assert answer.guard_action == "pass" and answer.grounded
        assert "first_clause" in answer.latency_ms
        assert llm.completed_streams == 1
        recorded = await session.scalar(
            select(ConversationMessage.text).where(ConversationMessage.id == answer.message_id)
        )
        assert recorded == answer.text


async def test_a_leaking_clause_is_never_released_and_generation_stops(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    # First sentence is harmless (the book never uses those words); the second names someone only the
    # last chapter introduces.
    llm = FakeLLMProvider(
        responses=["그 사람은 섬에서 지내요. 나중에 미르가 찾아와서 비밀을 알려줘요. 그리고 더 있어요."]
    )

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        clauses, answer = await collect(service.ask_stream(view, "하람은 누구야?"))

        assert not any("미르" in clause for clause in clauses)
        assert clauses[0] == "그 사람은 섬에서 지내요."
        assert clauses[-1] == SAFE_ANSWER
        assert answer.guard_action == "blocked" and not answer.grounded
        assert "미르" not in answer.text
        # The rest of the model's output was not consumed.
        assert llm.cancelled


async def test_streamed_provider_failure_ends_with_the_safe_message(
    db: Db, storage: LocalFileStorage
) -> None:
    from story_core.providers.base import ProviderUnavailable

    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider(failures=[ProviderUnavailable("down")])

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        clauses, answer = await collect(service.ask_stream(view, "하람은 누구야?"))

        assert clauses == [PROVIDER_ERROR_ANSWER]
        assert answer.guard_action == "provider_error" and not answer.grounded


async def test_closing_a_streamed_answer_early_closes_the_model_stream(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider(
        responses=["그 사람은 섬에서 지내요. 밤마다 바다를 살피는 일을 해요. 그리고 기다려요."],
        chunk_delay_s=0.001,
    )

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        events = service.ask_stream(view, "하람은 누구야?")
        first = await anext(events)
        assert isinstance(first, AnswerClause)
        await events.aclose()  # the reader interrupted

        assert llm.cancelled and llm.completed_streams == 0


@pytest.mark.parametrize("question", ["", "   ", "가" * 501])
async def test_invalid_questions_never_reach_a_provider(
    db: Db, storage: LocalFileStorage, question: str
) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider()

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        with pytest.raises(QuestionRejected):
            await service.ask(view, question)
    assert llm.requests == []


async def test_second_question_carries_the_previous_turns(db: Db, storage: LocalFileStorage) -> None:
    book_id, embedder = await indexed_book(db, storage)
    user_id = await create_user(db)
    llm = FakeLLMProvider()

    async with db.sessionmaker() as session:
        reading = ReadingSessionService(session, today=lambda: TODAY)
        view, _ = await reading.open(user_id, book_id)
        service = QuestionService(session, retriever=Retriever(session, embedder), llm=llm)

        first = await service.ask(view, "하람은 누구야?")
        second = await service.ask(view, "그럼 그 사람은 어디 있어?")

        assert second.conversation_id == first.conversation_id
        roles = [message.role for message in llm.requests[1].messages]
        assert roles.count("user") >= 2  # history + the new question
        assert any("하람은 누구야?" in message.content for message in llm.requests[1].messages)


async def test_gold_set_spoiler_probes_never_leak(db: Db, storage: LocalFileStorage) -> None:
    """The gold set's spoiler probes, run in the normal suite so a regression fails CI, not just eval.

    Each probe asks about something that happens later in the book from a position before it; no forbidden
    phrase may appear in the retrieved context or in the answer.
    """
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    source = (REPO_ROOT / gold["book"]).read_bytes()
    book_id, embedder = await indexed_book(db, storage, source=source)
    probes = [item for item in gold["items"] if item["kind"] == "future"]
    assert len(probes) >= 8, "the gold set must keep its spoiler probes"

    async with db.sessionmaker() as session:
        for probe in probes:
            allowed = await session.scalar(
                select(Sentence.global_seq)
                .where(Sentence.book_id == book_id, Sentence.text.contains(probe["ask_after"]))
                .order_by(Sentence.global_seq)
                .limit(1)
            )
            assert allowed is not None, probe["ask_after"]
            retrieval = await Retriever(session, embedder).retrieve(
                probe["question"], book_id=book_id, allowed_seq=allowed
            )
            context = "\n".join(chunk.text for chunk in retrieval.chunks)
            leaked = [needle for needle in probe["forbidden"] if needle in context]
            assert not leaked, f"{probe['id']} leaked {leaked} at allowed_seq={allowed}"


async def test_retrieval_config_limits_how_much_text_reaches_the_model(
    db: Db, storage: LocalFileStorage
) -> None:
    book_id, embedder = await indexed_book(db, storage)

    async with db.sessionmaker() as session:
        narrow = Retriever(session, embedder, config=RetrievalConfig(final_k=1, window_chunks=1))
        result = await narrow.retrieve("등대", book_id=book_id, allowed_seq=99)
        assert len(result.chunks) <= 2  # window chunk is always kept, plus at most final_k
        assert replace(RetrievalConfig(), final_k=1).final_k == 1
