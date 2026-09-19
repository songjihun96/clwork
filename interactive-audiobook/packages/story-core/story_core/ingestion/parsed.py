"""Format-independent parser output and shared text normalisation."""

import re
import unicodedata
from dataclasses import dataclass, field


class IngestionError(Exception):
    """Expected, user-fixable problem with a source file. ``code`` is stored on the book."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class ParsedParagraph:
    text: str
    scene_break_before: bool = False


@dataclass(slots=True)
class ParsedSection:
    title: str | None
    paragraphs: list[ParsedParagraph] = field(default_factory=list)


@dataclass(slots=True)
class ParsedChapter:
    title: str
    sections: list[ParsedSection] = field(default_factory=list)

    @property
    def paragraph_count(self) -> int:
        return sum(len(s.paragraphs) for s in self.sections)


@dataclass(slots=True)
class ParsedBook:
    title: str | None
    author: str | None
    chapters: list[ParsedChapter] = field(default_factory=list)


_WHITESPACE = re.compile(r"\s+")
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
# Lines that only mark a scene break: ***, * * *, ---, ◇◇◇, ○, ＊, ―――, #
_SCENE_BREAK = re.compile(r"^[\s*＊\-–—―_=~·•○●◇◆□■#]{1,20}$")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def is_scene_break(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(_SCENE_BREAK.match(stripped)) and not stripped.isalnum()


class ChapterBuilder:
    """Accumulates paragraphs into chapters/sections while tracking pending scene breaks."""

    def __init__(self) -> None:
        self.chapters: list[ParsedChapter] = []
        self._pending_break = False

    def start_chapter(self, title: str) -> None:
        self.chapters.append(ParsedChapter(title=title, sections=[ParsedSection(title=None)]))
        self._pending_break = False

    def start_section(self, title: str | None) -> None:
        if not self.chapters:
            self.start_chapter(title or "본문")
            return
        chapter = self.chapters[-1]
        if chapter.sections and not chapter.sections[-1].paragraphs and chapter.sections[-1].title is None:
            chapter.sections[-1].title = title
        else:
            chapter.sections.append(ParsedSection(title=title))

    def scene_break(self) -> None:
        self._pending_break = True

    def add_paragraph(self, raw: str, *, default_chapter_title: str = "본문") -> None:
        text = normalize_text(raw)
        if not text:
            return
        if is_scene_break(text):
            self.scene_break()
            return
        if not self.chapters:
            self.start_chapter(default_chapter_title)
        section = self.chapters[-1].sections[-1]
        section.paragraphs.append(ParsedParagraph(text=text, scene_break_before=self._pending_break))
        self._pending_break = False

    def result(self) -> list[ParsedChapter]:
        chapters = []
        for chapter in self.chapters:
            chapter.sections = [s for s in chapter.sections if s.paragraphs]
            if chapter.sections:
                chapters.append(chapter)
        return chapters
