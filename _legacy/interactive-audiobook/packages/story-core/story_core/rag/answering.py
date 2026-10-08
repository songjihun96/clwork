"""QuestionService: one text question about a book → one grounded answer.

This is the Phase 4 (text) form of what the realtime agent will call in Phase 6, so the ordering is the
one the voice path needs: position → spoiler window → retrieve → budgeted context → LLM → output guard →
persist. The LLM is the only step allowed to produce prose, and it is never given control over playback or
over how far the reader has got (docs/architecture.md §3.8).

Persistence is part of answering, not an afterthought: a spoiler complaint has to be auditable, and
evaluation needs to know which chunks grounded which answer.

Two entry points share everything but the generation step:

* ``ask`` - the text API. Generates the whole answer, guards it once, returns it.
* ``ask_stream`` - the voice path. Streams the model's output, cuts it into clauses, and guards **each
  clause before it is released**, so the first words can be spoken while the rest is still being written
  and nothing unguarded ever reaches the speaker. A clause that fails the guard ends the answer with the
  safe message; what was already released stays released, and is what gets recorded.
"""

import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from story_core.agent.clauses import ClauseChunker
from story_core.models.book import Chapter
from story_core.models.rag import Conversation, ConversationMessage
from story_core.models.reading import SpoilerMode
from story_core.providers.base import ProviderError, Usage
from story_core.providers.llm.base import LLMProvider, close_stream
from story_core.rag.context import BookContext, BuiltContext, ContextBuilder, HistoryTurn
from story_core.rag.retrieval import Retrieval, RetrievedChunk, Retriever
from story_core.rag.spoiler import SAFE_ANSWER, SpoilerGuard, SpoilerWindow, window_for
from story_core.reading.sessions import SessionView
from story_core.time import utcnow

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
HISTORY_TURNS = 4
UNGROUNDED_ANSWER = "책에서 그 내용을 찾지 못했어요."
PROVIDER_ERROR_ANSWER = "지금은 답하기 어려워요. 잠시 뒤에 다시 물어봐 주세요."


class QuestionRejected(Exception):
    """Invalid input (empty or too long). Never reaches a provider."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Citation:
    paragraph_id: uuid.UUID
    start_global_seq: int
    end_global_seq: int


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    grounded: bool
    allowed_seq: int
    spoiler_mode: SpoilerMode
    citations: list[Citation]
    guard_action: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    latency_ms: dict[str, int] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class AnswerClause:
    """A guarded piece of a streamed answer, ready to be spoken."""

    text: str


# ``ask_stream`` yields clauses, then exactly one ``Answer`` describing what was said.
AnswerEvent = AnswerClause | Answer


@dataclass(slots=True)
class _Prepared:
    text: str
    view: SessionView
    window: SpoilerWindow
    retrieval: Retrieval
    conversation_id: uuid.UUID
    built: BuiltContext
    started: float
    latency: dict[str, int]


class QuestionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        retriever: Retriever,
        llm: LLMProvider,
        context_builder: ContextBuilder | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._db = session
        self._retriever = retriever
        self._llm = llm
        self._context = context_builder or ContextBuilder()
        self._clock = clock

    async def ask(self, view: SessionView, question: str) -> Answer:
        prepared = await self._prepare(view, question)
        usage = prepared.retrieval.usage
        guard_action = "pass"
        llm_started = time.perf_counter()
        try:
            response = await self._llm.generate(prepared.built.request, timeout_s=30.0)
            answer_text = response.text.strip()
            usage = usage + response.usage
        except ProviderError as exc:
            logger.warning("question_llm_failed", extra={"error_type": type(exc).__name__})
            answer_text, guard_action = PROVIDER_ERROR_ANSWER, "provider_error"
        prepared.latency["llm"] = _ms(llm_started)

        if guard_action == "pass":
            if not prepared.retrieval.grounded and not answer_text:
                answer_text = UNGROUNDED_ANSWER
            if await self._leaks(prepared, answer_text):
                answer_text, guard_action = SAFE_ANSWER, "blocked"

        return await self._finish(prepared, answer_text, guard_action=guard_action, usage=usage)

    async def ask_stream(self, view: SessionView, question: str) -> AsyncGenerator[AnswerEvent]:
        """Clauses as soon as they are complete and guarded, then the recorded ``Answer``.

        Closing the iterator early (the reader interrupted) closes the model's stream too, so generation
        nobody will hear stops being paid for. An interrupted answer is not recorded yet: persisting from a
        cancelled task, and recording only what was actually heard, is Phase 7's job.
        """
        prepared = await self._prepare(view, question)
        usage = prepared.retrieval.usage
        guard_action = "pass"
        released: list[str] = []
        chunker = ClauseChunker()
        llm_started = time.perf_counter()

        async def admit(clause: str) -> bool:
            nonlocal guard_action
            if await self._leaks(prepared, clause):
                guard_action = "blocked"
                return False
            released.append(clause)
            if len(released) == 1:
                prepared.latency["first_clause"] = _ms(prepared.started)
            return True

        try:
            stream = self._llm.stream(prepared.built.request, timeout_s=30.0)
            try:
                async for chunk in stream:
                    if chunk.usage is not None:
                        usage = usage + chunk.usage
                    for clause in chunker.push(chunk.delta):
                        if not await admit(clause):
                            break
                        yield AnswerClause(clause)
                    if guard_action != "pass":
                        break
            finally:
                # Also on early exit: a blocked or interrupted answer must stop the generation upstream.
                await close_stream(stream)
            tail = chunker.flush() if guard_action == "pass" else None
            if tail and await admit(tail):
                yield AnswerClause(tail)
        except ProviderError as exc:
            logger.warning(
                "question_llm_failed",
                extra={"error_type": type(exc).__name__, "released_clauses": len(released)},
            )
            guard_action = "provider_error"
        prepared.latency["llm"] = _ms(llm_started)

        # One closing line when the answer could not be (fully) given. Released clauses stay said.
        closing = None
        if guard_action == "blocked":
            closing = SAFE_ANSWER
        elif guard_action == "provider_error":
            closing = PROVIDER_ERROR_ANSWER
        elif not released:
            closing = UNGROUNDED_ANSWER
        if closing is not None:
            yield AnswerClause(closing)
        spoken = " ".join([*released, *([closing] if closing else [])])
        yield await self._finish(prepared, spoken, guard_action=guard_action, usage=usage)

    # ------------------------------------------------------------------ shared steps

    async def _prepare(self, view: SessionView, question: str) -> _Prepared:
        text = question.strip()
        if not text:
            raise QuestionRejected("question_empty")
        if len(text) > MAX_QUESTION_CHARS:
            raise QuestionRejected("question_too_long")

        started = time.perf_counter()
        latency: dict[str, int] = {}
        window = window_for(
            position_seq=view.position.sentence_global_seq,
            max_read_seq=view.session.max_read_seq,
            mode=view.session.spoiler_mode,
            total_sentences=view.book.total_sentences,
            chapter_end_seq=await self._chapter_end_seq(view),
        )

        retrieval = await self._retriever.retrieve(text, book_id=view.book.id, allowed_seq=window.allowed_seq)
        latency.update(retrieval.timings_ms)

        conversation_id = await self._conversation_id(view)
        history = await self._history(conversation_id)
        built = self._context.build(
            question=text,
            book=BookContext(title=view.book.title, chapter_title=await self._chapter_title(view)),
            chunks=retrieval.chunks,
            history=history,
        )
        return _Prepared(text, view, window, retrieval, conversation_id, built, started, latency)

    async def _leaks(self, prepared: _Prepared, text: str) -> bool:
        guard_started = time.perf_counter()
        leaked = await SpoilerGuard(self._db, book_id=prepared.view.book.id).check(
            text, prepared.built.context_text, allowed=prepared.window.allowed_seq
        )
        prepared.latency["guard"] = prepared.latency.get("guard", 0) + _ms(guard_started)
        if leaked:
            # One regeneration would need a second provider call and a stricter prompt; until the
            # entity index exists (Phase 8) the safe answer is the honest behaviour.
            logger.warning(
                "spoiler_guard_blocked",
                extra={
                    "book_id": str(prepared.view.book.id),
                    "terms": len(leaked),
                    "allowed_seq": prepared.window.allowed_seq,
                },
            )
        return bool(leaked)

    async def _finish(
        self, prepared: _Prepared, answer_text: str, *, guard_action: str, usage: Usage
    ) -> Answer:
        prepared.latency["total"] = _ms(prepared.started)
        built = prepared.built
        citations = [
            Citation(
                paragraph_id=chunk.paragraph_id,
                start_global_seq=chunk.start_global_seq,
                end_global_seq=chunk.end_global_seq,
            )
            for chunk in built.used_chunks
        ]
        message_id = await self._persist(
            conversation_id=prepared.conversation_id,
            view=prepared.view,
            question=prepared.text,
            answer=answer_text,
            chunks=built.used_chunks,
            latency=prepared.latency,
            guard_action=guard_action,
            prompt_version=built.prompt_version,
        )
        return Answer(
            text=answer_text,
            grounded=prepared.retrieval.grounded and guard_action == "pass",
            allowed_seq=prepared.window.allowed_seq,
            spoiler_mode=prepared.window.mode,
            citations=citations,
            guard_action=guard_action,
            conversation_id=prepared.conversation_id,
            message_id=message_id,
            latency_ms=prepared.latency,
            usage=usage,
            provider=self._llm.info.provider,
            model=self._llm.info.model,
        )

    # ------------------------------------------------------------------ helpers

    async def _chapter_title(self, view: SessionView) -> str | None:
        if view.position.chapter_id is None:
            return None
        title = await self._db.scalar(select(Chapter.title).where(Chapter.id == view.position.chapter_id))
        return str(title) if title is not None else None

    async def _chapter_end_seq(self, view: SessionView) -> int | None:
        """Last sentence of the chapter being heard (LIGHT_SPOILER window)."""
        if view.position.chapter_id is None:
            return None
        row = (
            await self._db.execute(
                select(Chapter.first_sentence_seq, Chapter.sentence_count).where(
                    Chapter.id == view.position.chapter_id
                )
            )
        ).first()
        if row is None:
            return None
        return int(row.first_sentence_seq) + max(int(row.sentence_count) - 1, 0)

    async def _conversation_id(self, view: SessionView) -> uuid.UUID:
        existing = await self._db.scalar(
            select(Conversation.id)
            .where(Conversation.session_id == view.session.id)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return existing
        conversation = Conversation(
            id=uuid.uuid4(),
            session_id=view.session.id,
            user_id=view.session.user_id,
            last_active_at=self._clock(),
        )
        self._db.add(conversation)
        await self._db.flush()
        return conversation.id

    async def _history(self, conversation_id: uuid.UUID) -> list[HistoryTurn]:
        rows = (
            await self._db.execute(
                select(ConversationMessage.role, ConversationMessage.text)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
                .limit(HISTORY_TURNS * 2)
            )
        ).all()
        return [HistoryTurn(role=row.role, text=row.text) for row in reversed(rows)]

    async def _persist(
        self,
        *,
        conversation_id: uuid.UUID,
        view: SessionView,
        question: str,
        answer: str,
        chunks: list[RetrievedChunk],
        latency: dict[str, int],
        guard_action: str,
        prompt_version: str,
    ) -> uuid.UUID:
        now = self._clock()
        message_id = uuid.uuid4()
        self._db.add(
            ConversationMessage(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role="user",
                text=question,
                intent="BOOK_QUESTION",
                position_global_seq=view.position.sentence_global_seq,
                created_at=now,
            )
        )
        self._db.add(
            ConversationMessage(
                id=message_id,
                conversation_id=conversation_id,
                role="assistant",
                text=answer,
                intent="BOOK_QUESTION",
                position_global_seq=view.position.sentence_global_seq,
                retrieval_refs=[str(chunk.chunk_id) for chunk in chunks],
                latency_ms=latency,
                provider=self._llm.info.provider,
                model=self._llm.info.model,
                prompt_version=prompt_version,
                guard_action=guard_action,
                created_at=now,
            )
        )
        await self._db.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(last_active_at=now)
        )
        await self._db.commit()
        return message_id


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
