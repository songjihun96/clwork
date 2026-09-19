"""Korean-aware sentence splitting.

Sentences are the unit of narration, highlighting and resume ("끊긴 문장 처음부터 다시"), so a
boundary error is audible. Rules:

- A boundary follows terminal punctuation (. ? ! … and full-width forms), including any run of
  them ("?!", "……") and trailing closing quotes/brackets, when followed by whitespace or the end.
- No split inside quotation marks: a quoted utterance with several sentences stays one unit
  (splitting "안녕? 나는 모모야." into two would break the dialogue's intonation). The closing quote
  itself ends the unit, so an attribution that follows ("할머니가 말했다.") is the next sentence.
  If quotes are unbalanced within the paragraph (dialogue spanning paragraphs), quotes are ignored.
- Not a boundary: decimals (3.14), list markers at the start ("1. "), short Latin abbreviations
  ("Dr. ", "U.S. ").
- Units longer than ``max_chars`` are split at the last comma or space before the limit, because
  TTS providers degrade (or reject) very long inputs.

The implementation is swappable behind ``SentenceSplitter``; see scripts/eval_sentence_splitter.py
for the comparison against a morphological analyser.
"""

import re
from dataclasses import dataclass
from typing import Protocol

TERMINALS = frozenset(".?!…。？！")
CLOSERS = frozenset("\"'”’」』)]）〉》")
OPENING_TO_CLOSING = {"“": "”", "‘": "’", "「": "」", "『": "』", "《": "》", "〈": "〉"}
_LATIN_ABBREVIATION = re.compile(r"(?:^|[\s(])(?:[A-Za-z]{1,3}\.)+$")
_LIST_MARKER = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z]|[ivxIVX]{1,4})$")


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    start: int
    end: int
    text: str


class SentenceSplitter(Protocol):
    def split(self, paragraph: str) -> list[SentenceSpan]: ...


class RuleBasedKoreanSplitter:
    def __init__(self, *, max_chars: int = 300, max_quote_chars: int = 400) -> None:
        if max_chars < 20:
            raise ValueError("max_chars too small")
        self.max_chars = max_chars
        self.max_quote_chars = max_quote_chars

    def split(self, paragraph: str) -> list[SentenceSpan]:
        spans = self._split(paragraph, respect_quotes=True)
        if spans is None:  # unbalanced quotes
            spans = self._split(paragraph, respect_quotes=False) or []
        result: list[SentenceSpan] = []
        for span in spans:
            result.extend(self._enforce_max_length(paragraph, span))
        return result

    # ---------------------------------------------------------------------

    def _split(self, text: str, *, respect_quotes: bool) -> list[SentenceSpan] | None:
        spans: list[SentenceSpan] = []
        n = len(text)
        start = 0
        i = 0
        quote_stack: list[str] = []
        quote_opened_at = 0
        ascii_double_open = False

        while i < n:
            ch = text[i]

            if respect_quotes:
                if ch in OPENING_TO_CLOSING:
                    if not quote_stack:
                        quote_opened_at = i
                    quote_stack.append(OPENING_TO_CLOSING[ch])
                elif quote_stack and ch == quote_stack[-1]:
                    quote_stack.pop()
                elif ch == '"':
                    ascii_double_open = not ascii_double_open
                    if ascii_double_open and not quote_stack:
                        quote_opened_at = i

            if ch not in TERMINALS:
                i += 1
                continue

            # Consume the run of terminal punctuation ("?!", "...", "……").
            j = i
            while j < n and text[j] in TERMINALS:
                j += 1
            # Consume closing quotes/brackets, updating quote state.
            while j < n and text[j] in CLOSERS:
                closer = text[j]
                if respect_quotes:
                    if quote_stack and closer == quote_stack[-1]:
                        quote_stack.pop()
                    elif closer == '"':
                        ascii_double_open = not ascii_double_open
                j += 1

            at_boundary = j >= n or text[j].isspace()
            inside_quote = respect_quotes and (bool(quote_stack) or ascii_double_open)
            if inside_quote and i - quote_opened_at > self.max_quote_chars:
                inside_quote = False  # a very long quotation is split like normal prose

            if at_boundary and not inside_quote and not self._is_exception(text, start, i):
                self._append(spans, text, start, j)
                start = j
            i = j

        if respect_quotes and (quote_stack or ascii_double_open):
            return None
        self._append(spans, text, start, n)
        return spans

    @staticmethod
    def _is_exception(text: str, start: int, terminal_index: int) -> bool:
        if text[terminal_index] != ".":
            return False
        before = text[start:terminal_index]
        if _LIST_MARKER.match(before):
            return True
        return bool(_LATIN_ABBREVIATION.search(text[start : terminal_index + 1]))

    @staticmethod
    def _append(spans: list[SentenceSpan], text: str, start: int, end: int) -> None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append(SentenceSpan(start, end, text[start:end]))

    def _enforce_max_length(self, text: str, span: SentenceSpan) -> list[SentenceSpan]:
        pieces: list[SentenceSpan] = []
        start, end = span.start, span.end
        while end - start > self.max_chars:
            window = text[start : start + self.max_chars]
            cut = max(window.rfind(", "), window.rfind("，"))
            if cut > self.max_chars // 3:
                cut += 1  # keep the comma with the first piece
            else:
                cut = window.rfind(" ")
                if cut <= self.max_chars // 3:
                    cut = self.max_chars
            self._append(pieces, text, start, start + cut)
            start += cut
        self._append(pieces, text, start, end)
        return pieces
