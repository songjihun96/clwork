"""ContextBuilder: retrieved chunks → one prompt that fits a token budget.

There is no code path that puts a whole book in a prompt. The budget in docs/ai-architecture.md §3.4 is
enforced here, and when it is exceeded the order of sacrifice is fixed: **retrieved chunks first, then
conversation history** — the position window and the question are never dropped, because an answer about
the wrong place in the book is worse than an answer with less evidence.

Token counts are estimated, not tokenised: the tokenizer depends on the model, and pulling in one vendor's
BPE would both lie about other models and add a heavy dependency. The estimate is deliberately slightly
pessimistic for Korean, and real counts come back in provider usage.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from story_core.providers.llm.base import ChatMessage, LLMRequest, RequestTag
from story_core.rag.retrieval import RetrievedChunk

PROMPT_DIR = Path(__file__).parent / "prompts"
STORY_ANSWER_PROMPT = "story_answer.v1"
# Hangul syllables are ~1 token each for most multilingual tokenizers; ASCII runs ~4 chars per token.
_HANGUL = range(0xAC00, 0xD7A4)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Token budget per block (docs/ai-architecture.md §3.4)."""

    system: int = 400
    book_meta: int = 150
    position_window: int = 600
    retrieved: int = 1200
    history: int = 500
    question: int = 100

    @property
    def total(self) -> int:
        return (
            self.system
            + self.book_meta
            + self.position_window
            + self.retrieved
            + self.history
            + self.question
        )


@dataclass(frozen=True, slots=True)
class BookContext:
    title: str
    chapter_title: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    role: str
    text: str


@dataclass(frozen=True, slots=True)
class BuiltContext:
    request: LLMRequest
    # Exactly what was put in <context>, which is also what the spoiler guard treats as evidence.
    context_text: str
    used_chunks: list[RetrievedChunk]
    dropped_chunks: int
    dropped_history: int
    prompt_version: str
    estimated_tokens: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def estimate_tokens(text: str) -> int:
    """Rough token count: Hangul ≈ 1 token/char, other scripts ≈ 4 chars/token."""
    hangul = sum(1 for char in text if ord(char) in _HANGUL)
    other = len(text) - hangul
    return hangul + math.ceil(other / 4)


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"prompt template '{name}' is missing")
    return path.read_text(encoding="utf-8")


class ContextBuilder:
    def __init__(
        self,
        *,
        budget: ContextBudget | None = None,
        prompt_name: str = STORY_ANSWER_PROMPT,
        max_answer_tokens: int = 220,
    ) -> None:
        self._budget = budget or ContextBudget()
        self._prompt_name = prompt_name
        self._max_answer_tokens = max_answer_tokens

    def build(
        self,
        *,
        question: str,
        book: BookContext,
        chunks: Sequence[RetrievedChunk],
        history: Sequence[HistoryTurn] = (),
        request_tag: RequestTag = "story_answer",
    ) -> BuiltContext:
        window_chunks = [chunk for chunk in chunks if "window" in chunk.sources]
        searched = [chunk for chunk in chunks if "window" not in chunk.sources]

        kept_window, _ = _fit(window_chunks, self._budget.position_window)
        kept_searched, dropped = _fit(searched, self._budget.retrieved)
        used = sorted(kept_window + kept_searched, key=lambda chunk: chunk.start_global_seq)
        context_text = "\n".join(chunk.text for chunk in used)

        kept_history, dropped_history = _fit_history(history, self._budget.history)

        system = load_prompt(self._prompt_name).format(
            title=book.title,
            chapter=f" {book.chapter_title}" if book.chapter_title else "",
            context=context_text,
        )
        messages = [ChatMessage(role="system", content=system)]
        for turn in kept_history:
            messages.append(
                ChatMessage(role="assistant" if turn.role == "assistant" else "user", content=turn.text)
            )
        messages.append(ChatMessage(role="user", content=question[: self._budget.question * 4]))

        estimated = sum(estimate_tokens(message.content) for message in messages)
        notes: list[str] = []
        if dropped:
            notes.append(f"dropped_chunks={dropped}")
        if dropped_history:
            notes.append(f"dropped_history={dropped_history}")
        return BuiltContext(
            request=LLMRequest(
                messages=messages,
                max_tokens=self._max_answer_tokens,
                request_tag=request_tag,
                temperature=0.3,
            ),
            context_text=context_text,
            used_chunks=used,
            dropped_chunks=dropped,
            dropped_history=dropped_history,
            prompt_version=self._prompt_name,
            estimated_tokens=estimated,
            notes=tuple(notes),
        )


def _fit(chunks: Sequence[RetrievedChunk], budget: int) -> tuple[list[RetrievedChunk], int]:
    kept: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        cost = estimate_tokens(chunk.text)
        if kept and used + cost > budget:
            continue  # a later, smaller chunk may still fit
        if not kept and cost > budget:
            # Never return empty because one chunk is oversized: truncation beats no evidence.
            kept.append(chunk)
            used = cost
            continue
        kept.append(chunk)
        used += cost
    return kept, len(chunks) - len(kept)


def _fit_history(history: Sequence[HistoryTurn], budget: int) -> tuple[list[HistoryTurn], int]:
    kept: list[HistoryTurn] = []
    used = 0
    # Newest turns matter most for pronoun resolution, so fill from the end.
    for turn in reversed(history):
        cost = estimate_tokens(turn.text)
        if used + cost > budget:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept, len(history) - len(kept)
