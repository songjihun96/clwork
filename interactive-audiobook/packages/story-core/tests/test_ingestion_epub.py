import io
import zipfile

import pytest

from story_core.ingestion.epub_parser import EpubLimits, looks_like_epub, parse_epub
from story_core.ingestion.parsed import IngestionError
from tests.epub_factory import CONTAINER, SAMPLE_EPUB_DOCS, build_epub, xhtml


def test_parses_structure_metadata_and_scene_breaks() -> None:
    book = parse_epub(build_epub(SAMPLE_EPUB_DOCS))
    assert book.title == "등대지기의 밤" and book.author == "샘플"
    assert [c.title for c in book.chapters] == ["1장 · 바람이 바뀌던 날", "2장 · 낮게 뜬 불빛"]

    chapter1 = book.chapters[0]
    paragraphs = [p for s in chapter1.sections for p in s.paragraphs]
    assert [p.text for p in paragraphs] == [
        "섬의 끝에는 오래된 등대가 하나 서 있었다. 하얀 벽은 소금기에 바래 있었다.",
        "등대지기 하람은 매일 해 질 무렵 계단을 올랐다.",  # &nbsp; normalised
        "그날은 바람의 냄새가 달랐다.",
        "멀리서 작은 불빛 하나가 깜박였다.",  # untitled file continues the chapter
    ]
    assert [p.scene_break_before for p in paragraphs] == [False, False, True, False]
    assert all("alert" not in p.text for p in paragraphs)

    chapter2 = book.chapters[1]
    assert [s.title for s in chapter2.sections] == [None, "병 속의 편지"]
    assert chapter2.sections[1].paragraphs[0].text == "불빛은 유리병 안에서 흔들렸다. 병마개를 열었다."


def test_toc_titles_take_precedence_over_headings() -> None:
    docs = [("a.xhtml", xhtml("<p>첫 문장.</p>")), ("b.xhtml", xhtml("<h1>II</h1><p>둘째 문장.</p>"))]
    book = parse_epub(
        build_epub(docs, nav=[("text/a.xhtml", "프롤로그"), ("text/b.xhtml#top", "제2장 귀환")])
    )
    assert [c.title for c in book.chapters] == ["프롤로그", "제2장 귀환"]
    # A heading that differs from the TOC label is kept as a section title, not lost.
    assert book.chapters[1].sections[0].title == "II"


def test_non_linear_items_are_skipped() -> None:
    docs = [
        ("main.xhtml", xhtml("<h1>본문</h1><p>본문 문장.</p>")),
        ("notes.xhtml", xhtml("<h1>주석</h1><p>주석.</p>")),
    ]
    book = parse_epub(build_epub(docs, non_linear={"notes.xhtml"}))
    assert [c.title for c in book.chapters] == ["본문"]


def test_rejects_non_epub_and_missing_parts() -> None:
    with pytest.raises(IngestionError) as not_zip:
        parse_epub(b"hello")
    assert not_zip.value.code == "invalid_epub"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
    assert looks_like_epub(buffer.getvalue())
    with pytest.raises(IngestionError) as missing_opf:
        parse_epub(buffer.getvalue())
    assert missing_opf.value.code == "invalid_epub"


def test_rejects_zip_bomb_like_archives() -> None:
    bomb = build_epub(SAMPLE_EPUB_DOCS, extra_files={"OEBPS/zeros.bin": b"\0" * 5_000_000})
    with pytest.raises(IngestionError) as err:
        parse_epub(bomb, EpubLimits(max_compression_ratio=100))
    assert err.value.code == "epub_too_large"

    with pytest.raises(IngestionError) as too_many:
        parse_epub(build_epub(SAMPLE_EPUB_DOCS), EpubLimits(max_entries=3))
    assert too_many.value.code == "epub_too_complex"


def test_rejects_unsafe_paths() -> None:
    evil = build_epub(SAMPLE_EPUB_DOCS, extra_files={"../../etc/passwd": b"x"})
    with pytest.raises(IngestionError, match="unsafe"):
        parse_epub(evil)


def test_xml_entity_expansion_is_blocked() -> None:
    billion_laughs = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">&lol2;</container>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        archive.writestr("META-INF/container.xml", billion_laughs)
    with pytest.raises(IngestionError) as err:
        parse_epub(buffer.getvalue())
    assert err.value.code == "invalid_epub"


def test_book_without_text_is_empty() -> None:
    with pytest.raises(IngestionError) as err:
        parse_epub(build_epub([("cover.xhtml", xhtml('<img src="c.jpg"/>'))]))
    assert err.value.code == "empty_book"
