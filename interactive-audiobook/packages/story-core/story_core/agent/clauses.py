"""ClauseChunker: LLM token stream → clauses a TTS engine can start speaking (docs/realtime.md §5.2).

Time-to-first-audio is what the user feels, so the **first** clause is cut as early as a natural boundary
allows — even a very short one — and later clauses are allowed to grow, because a longer span gives the
engine room for natural intonation. Cutting everywhere would sound chopped; cutting nowhere means the user
hears nothing until the model finishes.

Korean gives good boundaries without parsing: sentence-final punctuation, and connective endings
("~하고", "~하지만", "~는데", "~해서") that almost always precede a clause break. A hard character cap
catches the case where the model produces a long run with no boundary at all.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# The first clause may be this short; anything shorter would be a syllable or two of audio.
FIRST_MIN_CHARS = 8
# Later clauses wait for a boundary at least this far in, so the engine has a phrase to work with.
LATER_MIN_CHARS = 24
# Emit regardless of boundaries beyond this, to bound latency and TTS request size.
MAX_CHARS = 120

# Closing quotes and brackets may follow the final punctuation of a sentence.
_SENTENCE_BOUNDARY = re.compile(r"[.!?…。！？]['\"”’)\]]*")  # noqa: RUF001
# Connective endings, checked at the end of the buffer followed by a space.
_CONNECTIVES = (
    "지만 ",
    "는데 ",
    "은데 ",
    "면서 ",
    "니까 ",
    "라서 ",
    "해서 ",
    "어서 ",
    "아서 ",
    "고요 ",
    "구요 ",
    "다가 ",
    "거나 ",
    "든지 ",
    "지요 ",
    "네요 ",
    "군요 ",
    "고 ",
)
_COMMA = re.compile(r"[,、]")


@dataclass
class ClauseChunker:
    """Push deltas, take whatever complete clauses fall out. ``flush`` returns the tail."""

    first_min_chars: int = FIRST_MIN_CHARS
    later_min_chars: int = LATER_MIN_CHARS
    max_chars: int = MAX_CHARS
    _buffer: str = field(default="", init=False)
    _emitted: int = field(default=0, init=False)

    @property
    def pending(self) -> str:
        return self._buffer

    @property
    def emitted(self) -> int:
        return self._emitted

    def push(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buffer += delta
        clauses: list[str] = []
        while True:
            cut = self._cut_point()
            if cut is None:
                break
            # The remainder is left-stripped so the length checks below mean what they say: a boundary
            # index must not be inflated by whitespace carried over from the previous clause.
            clause, self._buffer = self._buffer[:cut].strip(), self._buffer[cut:].lstrip()
            if clause:
                clauses.append(clause)
                self._emitted += 1
        return clauses

    def flush(self) -> str | None:
        """The remainder at end of stream — the last clause usually has no trailing space."""
        tail = self._buffer.strip()
        self._buffer = ""
        if not tail:
            return None
        self._emitted += 1
        return tail

    # ------------------------------------------------------------------ internals

    def _minimum(self) -> int:
        return self.first_min_chars if self._emitted == 0 else self.later_min_chars

    def _cut_point(self) -> int | None:
        """The earliest boundary at or after the minimum length — anywhere in the buffer, not just at its
        end. A delta can arrive with a boundary in the middle ("...예요. 그리고"), and only scanning the tail
        would hold that first clause back until the next boundary or the cap."""
        buffer = self._buffer
        minimum = self._minimum()
        if len(buffer.strip()) < minimum:
            # Not enough text to say yet; only the hard cap can force a cut.
            return len(buffer) if len(buffer) >= self.max_chars else None

        cuts: list[int] = []
        for match in _SENTENCE_BOUNDARY.finditer(buffer):
            if match.end() >= minimum:
                cuts.append(match.end())
                break
        for connective in _CONNECTIVES:
            index = buffer.find(connective, max(minimum - len(connective), 0))
            if index >= 0 and index + len(connective) >= minimum:
                cuts.append(index + len(connective))
        # A comma is a weaker boundary: only worth cutting once the clause is already substantial.
        for match in _COMMA.finditer(buffer):
            if match.end() >= max(minimum, self.later_min_chars):
                cuts.append(match.end())
                break
        if cuts:
            return min(cuts)
        if len(buffer) >= self.max_chars:
            return self._last_space(buffer) or len(buffer)
        return None

    @staticmethod
    def _last_space(buffer: str) -> int | None:
        index = buffer.rstrip().rfind(" ")
        return index + 1 if index > 0 else None


def split_clauses(text: str, **options: int) -> Iterator[str]:
    """Non-streaming convenience: the same boundaries applied to a finished string."""
    chunker = ClauseChunker(**options)
    yield from chunker.push(text)
    tail = chunker.flush()
    if tail:
        yield tail
