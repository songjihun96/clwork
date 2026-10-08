"""Plain-text (UTF-8) book parser.

Chapters start at heading lines such as "제1장 …", "1장", "Chapter 3", "프롤로그".
Paragraphs are separated by blank lines; files without blank lines use one paragraph per line.
"""

import re

from story_core.ingestion.parsed import ChapterBuilder, IngestionError, ParsedBook

_CHAPTER_HEADING = re.compile(
    r"^\s*(?:제\s*\d{1,4}\s*[장화부편막]|\d{1,4}\s*[장화]|chapter\s+\d{1,4}|part\s+\d{1,4}"
    r"|프롤로그|에필로그|서장|종장|prologue|epilogue)(?:[\s.:·\-–—].{0,50})?\s*$",
    re.IGNORECASE,
)
_MAX_HEADING_CHARS = 60


def decode_text(data: bytes) -> str:
    if b"\x00" in data:
        raise IngestionError("invalid_text_encoding", "Text files must not contain NUL bytes")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError("invalid_text_encoding", "Text files must be UTF-8 encoded") from exc


def parse_text(data: bytes) -> ParsedBook:
    text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        raise IngestionError("empty_book", "The text file has no content")

    # Count only blank lines *between* content (a trailing newline is not a paragraph separator).
    first = next(i for i, line in enumerate(lines) if line.strip())
    last = max(i for i, line in enumerate(lines) if line.strip())
    inner_blank = sum(1 for line in lines[first:last] if not line.strip())
    blank_separated = inner_blank >= max(1, len(non_empty) // 10)
    builder = ChapterBuilder()
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            builder.add_paragraph(" ".join(buffer))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if len(stripped) <= _MAX_HEADING_CHARS and _CHAPTER_HEADING.match(stripped):
            flush()
            builder.start_chapter(stripped)
            continue
        if blank_separated:
            buffer.append(stripped)
        else:
            builder.add_paragraph(stripped)
    flush()

    chapters = builder.result()
    if not chapters:
        raise IngestionError("empty_book", "The text file has no readable paragraphs")
    return ParsedBook(title=None, author=None, chapters=chapters)
