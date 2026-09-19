"""Paragraphs → retrieval chunks (docs/ai-architecture.md §3.1).

Two invariants make the spoiler filter exact, and every other decision here is subordinate to them:

1. a chunk covers a **contiguous run of sentences**, so ``end_global_seq`` is the highest sentence number
   it contains and ``end_global_seq <= allowed_seq`` can never hide a later sentence inside an earlier
   chunk;
2. a chunk never spans a chapter boundary or a scene break, so merging short paragraphs cannot pull
   context from a different place in the story.

Korean novels are dialogue-heavy — many paragraphs are a single short line — so short neighbours are
merged up to a target size, and long paragraphs are split at sentence boundaries. Merging is what makes
"누가 그렇게 말했어?" answerable: a lone "그럴 리 없어." embeds into nothing useful on its own.
"""

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# Sized for answer latency, not for maximum recall: retrieved text competes with the position window for
# the context budget (docs/ai-architecture.md §3.4).
TARGET_CHARS = 420
MAX_CHARS = 900
MAX_MERGED_PARAGRAPHS = 6


@dataclass(frozen=True, slots=True)
class SourceSentence:
    global_seq: int
    text: str


@dataclass(frozen=True, slots=True)
class SourceParagraph:
    """One paragraph as stored, with the sentences needed to split it."""

    paragraph_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_title: str
    global_seq: int
    scene_break_before: bool
    sentences: Sequence[SourceSentence]

    @property
    def text(self) -> str:
        return " ".join(sentence.text for sentence in self.sentences)


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_index: int
    paragraph_id: uuid.UUID
    chapter_id: uuid.UUID
    start_global_seq: int
    end_global_seq: int
    text: str
    # What gets embedded: a short location prefix helps the model place the passage. Stored text stays
    # clean so the answer prompt never shows scaffolding to the user.
    embed_text: str
    paragraph_count: int = 1

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.embed_text.encode()).hexdigest()


@dataclass(slots=True)
class _Group:
    paragraphs: list[SourceParagraph] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(paragraph.text) for paragraph in self.paragraphs)


def _embed_text(chapter_title: str, text: str) -> str:
    title = chapter_title.strip()
    return f"[{title}] {text}" if title else text


def _split_long(paragraph: SourceParagraph, *, max_chars: int) -> list[list[SourceSentence]]:
    """Split at sentence boundaries. A single sentence longer than the limit stays whole — the ingestion
    splitter already caps sentence length, and cutting mid-sentence would break the seq invariant."""
    pieces: list[list[SourceSentence]] = []
    current: list[SourceSentence] = []
    size = 0
    for sentence in paragraph.sentences:
        if current and size + len(sentence.text) > max_chars:
            pieces.append(current)
            current, size = [], 0
        current.append(sentence)
        size += len(sentence.text) + 1
    if current:
        pieces.append(current)
    return pieces


def build_chunks(
    paragraphs: Iterable[SourceParagraph],
    *,
    target_chars: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
    max_merged: int = MAX_MERGED_PARAGRAPHS,
) -> list[Chunk]:
    ordered = [p for p in sorted(paragraphs, key=lambda p: p.global_seq) if p.sentences]
    chunks: list[Chunk] = []
    group = _Group()

    def flush() -> None:
        if group.paragraphs:
            chunks.append(_chunk_of(group.paragraphs, len(chunks)))
            group.paragraphs = []

    for paragraph in ordered:
        breaks_group = bool(group.paragraphs) and (
            paragraph.scene_break_before
            or paragraph.chapter_id != group.paragraphs[-1].chapter_id
            or paragraph.global_seq != group.paragraphs[-1].global_seq + 1
            or len(group.paragraphs) >= max_merged
            or group.chars + len(paragraph.text) > target_chars
        )
        if breaks_group:
            flush()
        if len(paragraph.text) > max_chars:
            flush()
            for piece in _split_long(paragraph, max_chars=max_chars):
                chunks.append(_chunk_of([paragraph], len(chunks), sentences=piece))
            continue
        group.paragraphs.append(paragraph)
    flush()
    return chunks


def _chunk_of(
    paragraphs: Sequence[SourceParagraph], index: int, *, sentences: Sequence[SourceSentence] | None = None
) -> Chunk:
    first = paragraphs[0]
    if sentences is None:
        sentences = [sentence for paragraph in paragraphs for sentence in paragraph.sentences]
        text = "\n".join(paragraph.text for paragraph in paragraphs)
    else:
        text = " ".join(sentence.text for sentence in sentences)
    return Chunk(
        chunk_index=index,
        paragraph_id=first.paragraph_id,
        chapter_id=first.chapter_id,
        start_global_seq=sentences[0].global_seq,
        end_global_seq=sentences[-1].global_seq,
        text=text,
        embed_text=_embed_text(first.chapter_title, text),
        paragraph_count=len(paragraphs),
    )
