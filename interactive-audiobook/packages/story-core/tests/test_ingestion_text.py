import pytest

from story_core.ingestion.parsed import IngestionError, is_scene_break, normalize_text
from story_core.ingestion.sentences import RuleBasedKoreanSplitter
from story_core.ingestion.text_parser import parse_text
from tests.sentence_gold import GOLD


@pytest.mark.parametrize(("paragraph", "expected"), GOLD)
def test_sentence_gold_set(paragraph: str, expected: list[str]) -> None:
    spans = RuleBasedKoreanSplitter().split(paragraph)
    assert [s.text for s in spans] == expected
    for span in spans:  # offsets point back into the paragraph
        assert paragraph[span.start : span.end] == span.text


def test_long_sentence_is_split_for_tts() -> None:
    clause = "바람이 불었고, 파도가 높아졌고, 등대의 불빛은 점점 흐려졌다"
    paragraph = ", ".join([clause] * 12) + "."
    spans = RuleBasedKoreanSplitter(max_chars=120).split(paragraph)
    assert len(spans) > 1
    assert all(len(s.text) <= 120 for s in spans)
    assert "".join(paragraph[s.start : s.end] for s in spans).replace(" ", "") == paragraph.replace(" ", "")


def test_normalization_and_scene_breaks() -> None:
    assert normalize_text("  하람은​  계단을\n올랐다.  ") == "하람은 계단을 올랐다."
    for marker in ("***", "* * *", "◇◇◇", "―――", "#"):
        assert is_scene_break(marker)
    for prose in ("그래.", "1", "A"):
        assert not is_scene_break(prose)


def test_text_parser_chapters_paragraphs_and_breaks() -> None:
    source = (
        "제1장 바람이 바뀌던 날\n\n"
        "섬의 끝에는 등대가 있었다.\n하람은 계단을 올랐다.\n\n"
        "* * *\n\n"
        "밤이 되었다.\n\n"
        "2장 낮게 뜬 불빛\n\n"
        "불빛이 깜박였다.\n"
    ).encode()
    book = parse_text(source)
    assert [c.title for c in book.chapters] == ["제1장 바람이 바뀌던 날", "2장 낮게 뜬 불빛"]
    first = book.chapters[0].sections[0].paragraphs
    assert [p.text for p in first] == ["섬의 끝에는 등대가 있었다. 하람은 계단을 올랐다.", "밤이 되었다."]
    assert [p.scene_break_before for p in first] == [False, True]


def test_text_parser_line_per_paragraph_files() -> None:
    book = parse_text("첫 문단이다.\n둘째 문단이다.\n셋째 문단이다.\n".encode())
    assert book.chapters[0].title == "본문"
    assert len(book.chapters[0].sections[0].paragraphs) == 3


def test_text_parser_rejects_bad_input() -> None:
    with pytest.raises(IngestionError, match="UTF-8") as err:
        parse_text("등대".encode("cp949"))
    assert err.value.code == "invalid_text_encoding"
    with pytest.raises(IngestionError) as empty:
        parse_text(b"\n\n   \n")
    assert empty.value.code == "empty_book"
    with pytest.raises(IngestionError):
        parse_text(b"abc\x00def")


def test_text_parser_accepts_bom() -> None:
    book = parse_text("﻿본문이다.".encode())
    assert book.chapters[0].sections[0].paragraphs[0].text == "본문이다."
