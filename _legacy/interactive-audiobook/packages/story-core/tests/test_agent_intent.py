"""IntentRouter: rules, state dependence, and what happens when the classifier is not there.

The asymmetry being tested: a playback command must never be mistaken for a question *or* the other way
round, and when nothing is sure the router must land on BOOK_QUESTION — the recoverable mistake.
"""

import pytest

from story_core.agent.intent import (
    IntentDecision,
    PlaybackCommand,
    classify_by_rule,
    normalize,
    parse_classifier_output,
)
from story_core.agent.router import IntentRouter
from story_core.providers.base import ProviderUnavailable
from story_core.providers.llm.fake import FakeLLMProvider
from story_core.reading.state_machine import Intent, ReadingState

READING = ReadingState.READING
WAITING = ReadingState.AWAITING_FOLLOWUP


def rule(text: str, state: ReadingState = READING) -> IntentDecision | None:
    return classify_by_rule(text, state)


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("멈춰", PlaybackCommand.PAUSE),
        ("멈춰줘", PlaybackCommand.PAUSE),
        ("일시정지", PlaybackCommand.PAUSE),
        ("계속 읽어줘", PlaybackCommand.RESUME),
        ("이어서 읽어줘", PlaybackCommand.RESUME),
        ("다시 읽어줘", PlaybackCommand.REPEAT),
        ("빨리", PlaybackCommand.FASTER),
        ("더 천천히", PlaybackCommand.SLOWER),
        ("앞 문단", PlaybackCommand.PREV_PARAGRAPH),
        ("다음 문장", PlaybackCommand.NEXT_SENTENCE),
        ("그만 읽어", PlaybackCommand.STOP),
    ],
)
def test_playback_commands_are_decided_by_rules(text: str, command: PlaybackCommand) -> None:
    decided = rule(text)
    assert decided is not None and decided.source == "rule"
    assert decided.command is command
    assert decided.is_playback


@pytest.mark.parametrize(
    ("command", "intent"),
    [
        (PlaybackCommand.PAUSE, Intent.PLAYBACK_PAUSE),
        (PlaybackCommand.STOP, Intent.PLAYBACK_STOP),
        (PlaybackCommand.RESUME, Intent.PLAYBACK_RESUME),
        (PlaybackCommand.NEXT_SENTENCE, Intent.PLAYBACK_RESUME),
    ],
)
def test_playback_commands_map_onto_state_machine_intents(command: PlaybackCommand, intent: Intent) -> None:
    """Seeking and speed changes keep playback going, so the machine sees them as RESUME."""
    text = {v: k for k, v in _COMMAND_TEXT.items()}[command]
    decided = rule(text)
    assert decided is not None and decided.intent is intent


_COMMAND_TEXT = {
    "멈춰": PlaybackCommand.PAUSE,
    "그만": PlaybackCommand.STOP,
    "계속": PlaybackCommand.RESUME,
    "다음 문장": PlaybackCommand.NEXT_SENTENCE,
}


def test_acknowledgement_only_counts_while_waiting_for_a_follow_up() -> None:
    waiting = rule("응", WAITING)
    assert waiting is not None and waiting.intent is Intent.ACK

    # Mid-narration the same word is the listener agreeing, not an instruction.
    reading = rule("응", READING)
    assert reading is not None and reading.intent is Intent.UNCLEAR


@pytest.mark.parametrize("text", ["잠깐", "잠깐만", "저기요", "질문 있어"])
def test_attention_grabbers_are_interrupt_only(text: str) -> None:
    decided = rule(text)
    assert decided is not None and decided.intent is Intent.INTERRUPT_ONLY


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("줄거리 알려줘", Intent.SUMMARY),
        ("요약해줘", Intent.SUMMARY),
        ("지금 어디야", Intent.SCENE_QUESTION),
        ("이 장면 설명해줘", Intent.SCENE_QUESTION),
    ],
)
def test_summary_and_scene_phrases_are_decided_by_rules(text: str, intent: Intent) -> None:
    decided = rule(text)
    assert decided is not None and decided.intent is intent


@pytest.mark.parametrize(
    "text",
    [
        "하람은 왜 등대에 올라갔어?",
        "그 사람이 편지를 쓴 이유가 뭐야",
        "멈춰 있는 시계가 무슨 의미야?",  # contains a command word but is a question
        "계속 읽어달라고 한 사람이 누구야?",
        "원형극장이 뭐야?",
    ],
)
def test_rules_decline_on_anything_that_looks_like_a_sentence(text: str) -> None:
    """A long utterance is never decided by the dictionary, even when a command word appears in it."""
    assert rule(text) is None


def test_silence_is_unclear() -> None:
    for text in ("", "   ", "...", "음"):
        decided = rule(text)
        assert decided is not None and decided.intent is Intent.UNCLEAR, text


def test_normalisation_ignores_punctuation_spacing_and_case() -> None:
    assert normalize("  멈춰!!  ") == "멈춰"
    assert normalize("OK, 계속?") == "ok 계속"


async def test_router_uses_the_classifier_only_when_rules_decline() -> None:
    llm = FakeLLMProvider(responses=['{"intent": "GENERAL"}'])
    router = IntentRouter(llm)

    by_rule = await router.route("멈춰", READING)
    assert by_rule.source == "rule" and llm.requests == []

    by_llm = await router.route("원형극장이 뭐야?", READING)
    assert by_llm.source == "llm" and by_llm.intent is Intent.GENERAL
    assert llm.requests[0].request_tag == "intent"
    assert llm.requests[0].max_tokens <= 16  # the user is waiting in silence


async def test_router_falls_back_to_a_book_question_when_the_classifier_fails() -> None:
    llm = FakeLLMProvider(failures=[ProviderUnavailable("down")])
    router = IntentRouter(llm)

    decision = await router.route("그 사람이 왜 그런 말을 했을까", READING)

    assert decision.intent is Intent.BOOK_QUESTION
    assert decision.source == "fallback"
    assert router.fallbacks == 1


async def test_router_rejects_a_classifier_answer_outside_the_enum() -> None:
    for bad in ('{"intent": "PLAYBACK_STOP"}', '{"intent": "nonsense"}', "not json", "{}"):
        router = IntentRouter(FakeLLMProvider(responses=[bad]))
        decision = await router.route("이게 무슨 뜻이야 정확히", READING)
        assert decision.intent is Intent.BOOK_QUESTION, bad
        assert decision.source == "fallback"


async def test_router_without_a_classifier_still_answers() -> None:
    router = IntentRouter(None)
    decision = await router.route("하람은 왜 그랬어?", READING)
    assert decision.intent is Intent.BOOK_QUESTION and decision.source == "fallback"


def test_classifier_output_parsing() -> None:
    assert parse_classifier_output('{"intent": "SUMMARY"}') is Intent.SUMMARY
    assert parse_classifier_output('{"intent": "ACK"}') is None  # not the classifier's to choose
    assert parse_classifier_output('{"intent": 3}') is None
