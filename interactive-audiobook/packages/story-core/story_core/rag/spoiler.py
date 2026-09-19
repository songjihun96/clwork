"""Spoiler defence: how far the reader may be told about, and a check on what the model said.

Layer 1 (the query filter) lives in :mod:`story_core.rag.search`; this module owns layer 1's input
(``allowed_seq``) and layer 4 (the output check). See docs/ai-architecture.md §3.3.

``allowed_seq`` uses ``max_read_seq``, not the current position: re-reading an earlier chapter must not
make the reader forget what they already heard — it would be absurd for the agent to refuse to discuss a
character it just narrated because the user scrolled back.

The output check exists because the model may know the book from pre-training and leak an ending that was
never retrieved. It only inspects what the answer added *beyond its evidence*: terms already present in
the context are allowed by construction, so a term is looked up only when the model introduced it. Phase 8
replaces the lookup with ``characters.first_appearance_seq``; until then a term is "future" when it does
not occur in the book at or before ``allowed_seq`` but does occur after it.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from story_core.models.book import Sentence
from story_core.models.reading import SpoilerMode

# Anything shorter is too common to be a name and would make the check noisy.
MIN_TERM_LENGTH = 2
MAX_CHECKED_TERMS = 12
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
# Korean attaches particles to names ("모모가", "등대에서"), so a term is also
# checked with its tail removed.
_PARTICLES = (
    "이라고",
    "라고",
    "에서",
    "으로",
    "에게",
    "께서",
    "이랑",
    "하고",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "도",
    "만",
    "과",
    "와",
    "로",
)

GuardAction = Literal["pass", "blocked"]

SAFE_ANSWER = "그건 아직 읽지 않은 부분이라 말해줄 수 없어요."


@dataclass(frozen=True, slots=True)
class SpoilerWindow:
    allowed_seq: int
    mode: SpoilerMode


def allowed_seq(
    *,
    position_seq: int,
    max_read_seq: int,
    mode: SpoilerMode | str,
    total_sentences: int,
    chapter_end_seq: int | None = None,
) -> int:
    """The highest sentence number that may be used to answer."""
    heard = max(position_seq, max_read_seq, 0)
    last = max(total_sentences - 1, 0)
    resolved = SpoilerMode(mode)
    if resolved is SpoilerMode.FULL_SPOILER:
        return last
    if resolved is SpoilerMode.LIGHT_SPOILER:
        # Provisional definition (docs/ai-architecture.md §3.3): to the end of the chapter being heard.
        # Anything looser needs a product decision, so the code stays at the conservative reading.
        return min(max(heard, chapter_end_seq if chapter_end_seq is not None else heard), last)
    return min(heard, last)


def window_for(
    *,
    position_seq: int,
    max_read_seq: int,
    mode: SpoilerMode | str,
    total_sentences: int,
    chapter_end_seq: int | None = None,
) -> SpoilerWindow:
    return SpoilerWindow(
        allowed_seq=allowed_seq(
            position_seq=position_seq,
            max_read_seq=max_read_seq,
            mode=mode,
            total_sentences=total_sentences,
            chapter_end_seq=chapter_end_seq,
        ),
        mode=SpoilerMode(mode),
    )


def _variants(term: str) -> list[str]:
    variants = [term]
    for particle in _PARTICLES:
        if len(term) > len(particle) + 1 and term.endswith(particle):
            variants.append(term[: -len(particle)])
            break
    return variants


def novel_terms(answer: str, context: str, *, limit: int = MAX_CHECKED_TERMS) -> list[str]:
    """Terms the answer introduced that its evidence does not contain."""
    haystack = context
    found: dict[str, None] = {}
    for token in _TOKEN.findall(answer):
        if len(token) < MIN_TERM_LENGTH:
            continue
        if any(variant in haystack for variant in _variants(token)):
            continue
        found.setdefault(token, None)
    # Longest first: a leaked proper noun is usually the longest novel token.
    return sorted(found, key=lambda term: (-len(term), term))[:limit]


class SpoilerGuard:
    """Checks an answer against the book. One DB round trip, only for terms the model introduced."""

    def __init__(self, session: AsyncSession, *, book_id: uuid.UUID) -> None:
        self._session = session
        self._book_id = book_id

    async def future_terms(self, terms: Sequence[str], *, allowed: int) -> list[str]:
        if not terms:
            return []
        # One statement: per term, the first sentence number it appears in (any variant).
        branches = []
        for index, term in enumerate(terms):
            patterns = [f"%{variant}%" for variant in _variants(term)]
            condition = or_(*(Sentence.text.like(pattern) for pattern in patterns))
            branches.append(
                select(literal(index).label("idx"), func.min(Sentence.global_seq).label("first_seq")).where(
                    Sentence.book_id == self._book_id, condition
                )
            )
        rows = (await self._session.execute(union_all(*branches))).all()
        leaked = []
        for row in rows:
            first_seq = row.first_seq
            # Not in the book at all → not a spoiler (general knowledge, or the model's own wording).
            if first_seq is not None and first_seq > allowed:
                leaked.append(terms[int(row.idx)])
        return leaked

    async def check(self, answer: str, context: str, *, allowed: int) -> list[str]:
        return await self.future_terms(novel_terms(answer, context), allowed=allowed)


def contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)
