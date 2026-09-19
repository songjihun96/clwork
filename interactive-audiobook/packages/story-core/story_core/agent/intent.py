"""IntentRouter: what the user just said, as an enum (docs/ai-architecture.md §2).

Rules first, and they are deliberately narrow. A misrouted playback command is the worst outcome — "멈춰"
answered with a paragraph of prose, or a real question swallowed as a command — so a rule fires only on a
short utterance that matches a known phrase, and everything else falls through to the model.

Three properties are load-bearing:

* **the same words mean different things per state.** "응" is an acknowledgement while the agent waits for a
  follow-up, and nothing at all in the middle of narration (it is the listener agreeing, not a command).
* **rules never guess.** Anything longer than a few words, or not in the dictionary, is `None` here and goes
  to the small classifier, which may fail closed to `BOOK_QUESTION` — the safe default, since a question
  answered from the book is recoverable and a wrongly-stopped narration is not.
* **no I/O.** The rule layer is a pure function so it can be swept over a labelled set in milliseconds.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from story_core.reading.state_machine import Intent, ReadingState

# Rules only apply to short utterances; a long sentence containing "멈춰" is probably a question about it.
MAX_RULE_WORDS = 4
DecisionSource = Literal["rule", "llm", "fallback"]


class PlaybackCommand(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    REPEAT = "REPEAT"
    FASTER = "FASTER"
    SLOWER = "SLOWER"
    NEXT_SENTENCE = "NEXT_SENTENCE"
    PREV_SENTENCE = "PREV_SENTENCE"
    NEXT_PARAGRAPH = "NEXT_PARAGRAPH"
    PREV_PARAGRAPH = "PREV_PARAGRAPH"


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: Intent
    source: DecisionSource
    command: PlaybackCommand | None = None
    confidence: float = 1.0

    @property
    def is_playback(self) -> bool:
        return self.command is not None


# Normalised phrase → intent. Written as the user says them, including the polite forms.
_PLAYBACK: dict[str, PlaybackCommand] = {
    "멈춰": PlaybackCommand.PAUSE,
    "멈춰줘": PlaybackCommand.PAUSE,
    "잠깐멈춰": PlaybackCommand.PAUSE,
    "일시정지": PlaybackCommand.PAUSE,
    "스톱": PlaybackCommand.PAUSE,
    "계속": PlaybackCommand.RESUME,
    "계속읽어": PlaybackCommand.RESUME,
    "계속읽어줘": PlaybackCommand.RESUME,
    "다시재생": PlaybackCommand.RESUME,
    "이어서읽어줘": PlaybackCommand.RESUME,
    "그만": PlaybackCommand.STOP,
    "그만읽어": PlaybackCommand.STOP,
    "종료": PlaybackCommand.STOP,
    "끝내줘": PlaybackCommand.STOP,
    "다시읽어줘": PlaybackCommand.REPEAT,
    "다시읽어": PlaybackCommand.REPEAT,
    "한번더": PlaybackCommand.REPEAT,
    "빨리": PlaybackCommand.FASTER,
    "빠르게": PlaybackCommand.FASTER,
    "더빨리": PlaybackCommand.FASTER,
    "천천히": PlaybackCommand.SLOWER,
    "느리게": PlaybackCommand.SLOWER,
    "더천천히": PlaybackCommand.SLOWER,
    "다음문장": PlaybackCommand.NEXT_SENTENCE,
    "다음": PlaybackCommand.NEXT_SENTENCE,
    "이전문장": PlaybackCommand.PREV_SENTENCE,
    "앞문장": PlaybackCommand.PREV_SENTENCE,
    "다음문단": PlaybackCommand.NEXT_PARAGRAPH,
    "앞문단": PlaybackCommand.PREV_PARAGRAPH,
    "이전문단": PlaybackCommand.PREV_PARAGRAPH,
}

_ACK = frozenset(
    {"응", "웅", "어", "네", "예", "그래", "알겠어", "알았어", "오케이", "오키", "좋아", "됐어", "고마워"}
)

# Hesitation noises. Worth a rule of their own: they are the most common thing a microphone picks up, and
# sending each one to the classifier would spend a model call on silence.
_FILLERS = frozenset({"음", "흠", "아", "그", "저", "에", "뭐", "어요", "그니까", "그러니까"})

_INTERRUPT_ONLY = frozenset(
    {"잠깐", "잠깐만", "저기", "저기요", "잠시만", "질문", "질문있어", "물어볼게", "물어볼게있어", "야"}
)

# Phrases that are always a summary request, even though they look like questions.
_SUMMARY = frozenset(
    {"줄거리", "줄거리알려줘", "지금까지줄거리", "요약", "요약해줘", "지금까지어떻게됐어", "무슨일이있었어"}
)

# "Where am I" style questions are about the scene, not the plot.
_SCENE = frozenset({"지금어디야", "여기어디야", "이장면설명해줘", "무슨장면이야", "어디쯤이야"})

_PUNCTUATION = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ\s]+")
_SPACES = re.compile(r"\s+")
# Trailing politeness and fillers that do not change the meaning of a short command.
_TAILS = ("주세요", "해주세요", "해줘", "please", "요")


def normalize(text: str) -> str:
    """Lower-cased, punctuation-free, space-free form used for dictionary matching."""
    folded = unicodedata.normalize("NFKC", text).strip().casefold()
    folded = _PUNCTUATION.sub(" ", folded)
    return _SPACES.sub(" ", folded).strip()


def _key(text: str) -> str:
    return normalize(text).replace(" ", "")


def _strip_tail(key: str) -> str:
    for tail in _TAILS:
        if len(key) > len(tail) + 1 and key.endswith(tail):
            return key[: -len(tail)]
    return key


def word_count(text: str) -> int:
    return len(normalize(text).split())


def classify_by_rule(text: str, state: ReadingState) -> IntentDecision | None:
    """The 0 ms layer. Returns None when it is not confident — that is the common case."""
    key = _key(text)
    if not key:
        return IntentDecision(Intent.UNCLEAR, source="rule")
    if word_count(text) > MAX_RULE_WORDS:
        return None

    for candidate in (key, _strip_tail(key)):
        command = _PLAYBACK.get(candidate)
        if command is not None:
            return IntentDecision(_playback_intent(command), source="rule", command=command)
        if candidate in _SUMMARY:
            return IntentDecision(Intent.SUMMARY, source="rule")
        if candidate in _SCENE:
            return IntentDecision(Intent.SCENE_QUESTION, source="rule")
        if candidate in _ACK:
            # Only meaningful while the agent is waiting; mid-narration it is the listener agreeing.
            if state is ReadingState.AWAITING_FOLLOWUP:
                return IntentDecision(Intent.ACK, source="rule")
            return IntentDecision(Intent.UNCLEAR, source="rule")
        if candidate in _FILLERS:
            return IntentDecision(Intent.UNCLEAR, source="rule")
        if candidate in _INTERRUPT_ONLY:
            return IntentDecision(Intent.INTERRUPT_ONLY, source="rule")
    return None


def _playback_intent(command: PlaybackCommand) -> Intent:
    if command is PlaybackCommand.PAUSE:
        return Intent.PLAYBACK_PAUSE
    if command is PlaybackCommand.STOP:
        return Intent.PLAYBACK_STOP
    # Resume, repeat, speed and seeking all continue playback from the state machine's point of view.
    return Intent.PLAYBACK_RESUME


# The classifier's output shape. Guided decoding keeps the model inside this set.
INTENT_SCHEMA: dict[str, object] = {
    "name": "intent",
    "schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    Intent.BOOK_QUESTION,
                    Intent.SCENE_QUESTION,
                    Intent.SUMMARY,
                    Intent.GENERAL,
                    Intent.INTERRUPT_ONLY,
                    Intent.UNCLEAR,
                ],
            }
        },
        "required": ["intent"],
        "additionalProperties": False,
    },
    "strict": True,
}

_CLASSIFIER_INTENTS = {
    Intent.BOOK_QUESTION,
    Intent.SCENE_QUESTION,
    Intent.SUMMARY,
    Intent.GENERAL,
    Intent.INTERRUPT_ONLY,
    Intent.UNCLEAR,
}

CLASSIFIER_PROMPT = (
    "사용자가 오디오북을 듣는 중에 한 말을 분류한다. "
    "BOOK_QUESTION: 책 내용에 대한 질문. SCENE_QUESTION: 지금 어디를 읽고 있는지, 장면에 대한 질문. "
    "SUMMARY: 지금까지의 줄거리 요청. GENERAL: 책과 무관한 일반 지식 질문. "
    "INTERRUPT_ONLY: 말을 걸기만 한 것. UNCLEAR: 알아들을 수 없거나 의미 없는 말. "
    "재생 제어(멈춰·계속·빨리 등)는 이미 처리되었으므로 고르지 않는다. JSON만 출력한다."
)


def parse_classifier_output(raw: str) -> Intent | None:
    """Accept only the six intents the classifier is allowed to choose."""
    import json

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("intent")
    if not isinstance(value, str):
        return None
    try:
        intent = Intent(value)
    except ValueError:
        return None
    return intent if intent in _CLASSIFIER_INTENTS else None
