"""ReadingSession state machine (docs/realtime.md §3).

Pure and synchronous: ``transition(snapshot, event)`` returns the next snapshot plus the side
effects the caller must perform (stop audio, call the LLM, persist...). No I/O happens here, so
every rule is unit-testable and the same rules run in the API (Listen mode) and the realtime agent
(Talk mode).

The LLM never drives this machine directly. The intent router turns speech into a typed ``Intent``;
only these typed events can change playback.
"""

from dataclasses import dataclass, field, replace
from enum import StrEnum


class ReadingState(StrEnum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    READING = "READING"
    USER_SPEAKING = "USER_SPEAKING"
    PROCESSING_QUESTION = "PROCESSING_QUESTION"
    ANSWERING = "ANSWERING"
    AWAITING_FOLLOWUP = "AWAITING_FOLLOWUP"
    RESUMING = "RESUMING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class EventType(StrEnum):
    START = "START"
    READY = "READY"
    SENTENCE_DONE = "SENTENCE_DONE"
    SEEK = "SEEK"
    VAD_SPEECH_START = "VAD_SPEECH_START"
    CONTROL_ASK = "CONTROL_ASK"
    INTERRUPT_CONFIRMED = "INTERRUPT_CONFIRMED"
    FALSE_INTERRUPTION = "FALSE_INTERRUPTION"
    STT_FINAL = "STT_FINAL"
    ANSWER_FIRST_AUDIO = "ANSWER_FIRST_AUDIO"
    ANSWER_DONE = "ANSWER_DONE"
    ANSWER_FAILED = "ANSWER_FAILED"
    FOLLOWUP_TIMEOUT = "FOLLOWUP_TIMEOUT"
    BRIDGE_DONE = "BRIDGE_DONE"
    CONTROL_PAUSE = "CONTROL_PAUSE"
    CONTROL_RESUME = "CONTROL_RESUME"
    CONTROL_STOP = "CONTROL_STOP"
    FATAL = "FATAL"
    RETRY = "RETRY"


class Intent(StrEnum):
    BOOK_QUESTION = "BOOK_QUESTION"
    SCENE_QUESTION = "SCENE_QUESTION"
    SUMMARY = "SUMMARY"
    GENERAL = "GENERAL"
    PLAYBACK_PAUSE = "PLAYBACK_PAUSE"
    PLAYBACK_RESUME = "PLAYBACK_RESUME"
    PLAYBACK_STOP = "PLAYBACK_STOP"
    ACK = "ACK"
    INTERRUPT_ONLY = "INTERRUPT_ONLY"
    UNCLEAR = "UNCLEAR"


QUESTION_INTENTS = frozenset({Intent.BOOK_QUESTION, Intent.SCENE_QUESTION, Intent.SUMMARY, Intent.GENERAL})


class EffectType(StrEnum):
    LOAD_POSITION = "LOAD_POSITION"
    PLAY_NARRATION = "PLAY_NARRATION"
    DUCK_AUDIO = "DUCK_AUDIO"
    UNDUCK_AUDIO = "UNDUCK_AUDIO"
    STOP_NARRATION = "STOP_NARRATION"
    STOP_ANSWER = "STOP_ANSWER"
    STOP_BRIDGE = "STOP_BRIDGE"
    CANCEL_ANSWER = "CANCEL_ANSWER"
    ANSWER_QUESTION = "ANSWER_QUESTION"
    START_FOLLOWUP_TIMER = "START_FOLLOWUP_TIMER"
    CANCEL_FOLLOWUP_TIMER = "CANCEL_FOLLOWUP_TIMER"
    PLAY_BRIDGE = "PLAY_BRIDGE"
    PLAY_CUE = "PLAY_CUE"
    CHECKPOINT = "CHECKPOINT"
    PERSIST = "PERSIST"
    REPORT_ERROR = "REPORT_ERROR"


class Cue(StrEnum):
    """Short pre-rendered prompts (cached per voice)."""

    PARDON = "PARDON"  # "잘 못 들었어요, 다시 말해줄래요?"
    LISTENING = "LISTENING"  # "응, 말해줘."
    ANSWER_FAILED = "ANSWER_FAILED"  # "지금은 답하기 어려워요."


@dataclass(frozen=True, slots=True)
class Position:
    paragraph_id: str
    sentence_index: int


@dataclass(frozen=True, slots=True)
class Event:
    type: EventType
    intent: Intent | None = None
    position: Position | None = None
    """READY: start position. SEEK: target. SENTENCE_DONE: next sentence, or None at the end of the book."""
    retryable: bool = True


@dataclass(frozen=True, slots=True)
class Effect:
    type: EffectType
    position: Position | None = None
    cue: Cue | None = None


@dataclass(frozen=True, slots=True)
class MachineConfig:
    # Talk mode plays a cached "그럼 다시 이야기할게" before resuming; Listen mode resumes directly.
    bridge_phrase: bool = True


@dataclass(frozen=True, slots=True)
class Snapshot:
    state: ReadingState = ReadingState.IDLE
    position: Position | None = None
    """Sentence being read (or last read)."""
    interrupt_point: Position | None = None
    """Where reading resumes. Set once when leaving READING; consumed when READING restarts."""
    ducked: bool = False
    """Audio is still playing at reduced volume, waiting for the interruption to be confirmed."""
    retryable: bool = True

    @property
    def resume_position(self) -> Position | None:
        return self.interrupt_point or self.position


@dataclass(frozen=True, slots=True)
class Transition:
    snapshot: Snapshot
    effects: tuple[Effect, ...] = field(default_factory=tuple)
    ignored: bool = False


def _fx(*effects: Effect | EffectType) -> tuple[Effect, ...]:
    return tuple(e if isinstance(e, Effect) else Effect(e) for e in effects)


def _ignored(snapshot: Snapshot) -> Transition:
    return Transition(snapshot, (), ignored=True)


_TALKING_STATES = frozenset(
    {
        ReadingState.USER_SPEAKING,
        ReadingState.PROCESSING_QUESTION,
        ReadingState.ANSWERING,
        ReadingState.AWAITING_FOLLOWUP,
        ReadingState.RESUMING,
    }
)

_STOP_EVERYTHING = _fx(
    EffectType.STOP_NARRATION,
    EffectType.STOP_ANSWER,
    EffectType.STOP_BRIDGE,
    EffectType.CANCEL_ANSWER,
    EffectType.CANCEL_FOLLOWUP_TIMER,
)


def transition(snapshot: Snapshot, event: Event, config: MachineConfig | None = None) -> Transition:
    config = config or MachineConfig()
    s = snapshot
    state = s.state
    et = event.type

    # ---------- events valid from (almost) any state ----------
    if et is EventType.FATAL:
        if state is ReadingState.ERROR:
            return _ignored(s)
        # Recover to the last confirmed sentence, never into the middle of an answer.
        nxt = replace(s, state=ReadingState.ERROR, ducked=False, retryable=event.retryable)
        return Transition(
            nxt, (*_STOP_EVERYTHING, Effect(EffectType.PERSIST), Effect(EffectType.REPORT_ERROR))
        )

    if et is EventType.CONTROL_STOP:
        if state in (ReadingState.IDLE, ReadingState.ERROR):
            return _ignored(s)
        nxt = Snapshot(state=ReadingState.IDLE, position=s.resume_position)
        return Transition(nxt, (*_STOP_EVERYTHING, Effect(EffectType.PERSIST)))

    if et is EventType.CONTROL_PAUSE and (state is ReadingState.READING or state in _TALKING_STATES):
        nxt = replace(s, state=ReadingState.PAUSED, interrupt_point=s.resume_position, ducked=False)
        return Transition(nxt, (*_STOP_EVERYTHING, Effect(EffectType.PERSIST)))

    # ---------- per-state rules ----------
    match state:
        case ReadingState.IDLE:
            if et is EventType.START:
                return Transition(replace(s, state=ReadingState.PREPARING), _fx(EffectType.LOAD_POSITION))

        case ReadingState.PREPARING:
            if et is EventType.READY and event.position is not None:
                nxt = Snapshot(state=ReadingState.READING, position=event.position)
                return Transition(nxt, (Effect(EffectType.PLAY_NARRATION, event.position),))

        case ReadingState.READING:
            return _reading(s, event)

        case ReadingState.USER_SPEAKING:
            return _user_speaking(s, event, config)

        case ReadingState.PROCESSING_QUESTION:
            if et is EventType.ANSWER_FIRST_AUDIO:
                return Transition(replace(s, state=ReadingState.ANSWERING))
            if et is EventType.ANSWER_FAILED:
                nxt = replace(s, state=ReadingState.AWAITING_FOLLOWUP)
                return Transition(
                    nxt,
                    (
                        Effect(EffectType.PLAY_CUE, cue=Cue.ANSWER_FAILED),
                        Effect(EffectType.START_FOLLOWUP_TIMER),
                    ),
                )
            if et in (EventType.VAD_SPEECH_START, EventType.CONTROL_ASK):
                # The user keeps talking before the answer starts: drop the pending answer and listen again.
                return Transition(replace(s, state=ReadingState.USER_SPEAKING), _fx(EffectType.CANCEL_ANSWER))

        case ReadingState.ANSWERING:
            if et is EventType.ANSWER_DONE:
                return Transition(
                    replace(s, state=ReadingState.AWAITING_FOLLOWUP, ducked=False),
                    _fx(EffectType.START_FOLLOWUP_TIMER),
                )
            if et is EventType.VAD_SPEECH_START and not s.ducked:
                return Transition(replace(s, ducked=True), _fx(EffectType.DUCK_AUDIO))
            if et is EventType.FALSE_INTERRUPTION and s.ducked:
                return Transition(replace(s, ducked=False), _fx(EffectType.UNDUCK_AUDIO))
            if et in (EventType.INTERRUPT_CONFIRMED, EventType.CONTROL_ASK):
                return Transition(
                    replace(s, state=ReadingState.USER_SPEAKING, ducked=False),
                    _fx(EffectType.STOP_ANSWER, EffectType.CANCEL_ANSWER),
                )

        case ReadingState.AWAITING_FOLLOWUP:
            if et in (EventType.VAD_SPEECH_START, EventType.CONTROL_ASK):
                return Transition(
                    replace(s, state=ReadingState.USER_SPEAKING), _fx(EffectType.CANCEL_FOLLOWUP_TIMER)
                )
            if et is EventType.STT_FINAL:
                return _handle_utterance(s, event, config, narration_ducked=False, cancel_timer=True)
            if et in (EventType.FOLLOWUP_TIMEOUT, EventType.CONTROL_RESUME):
                return _resume(s, config)

        case ReadingState.RESUMING:
            if et is EventType.BRIDGE_DONE:
                return _start_reading_at_interrupt_point(s)
            if et in (EventType.VAD_SPEECH_START, EventType.CONTROL_ASK):
                return Transition(replace(s, state=ReadingState.USER_SPEAKING), _fx(EffectType.STOP_BRIDGE))

        case ReadingState.PAUSED:
            if et is EventType.CONTROL_RESUME:
                return _resume(s, config)
            if et is EventType.SEEK and event.position is not None:
                nxt = replace(s, position=event.position, interrupt_point=event.position)
                return Transition(
                    nxt, (Effect(EffectType.CHECKPOINT, event.position), Effect(EffectType.PERSIST))
                )

        case ReadingState.ERROR:
            if et is EventType.RETRY and s.retryable:
                return Transition(replace(s, state=ReadingState.PREPARING), _fx(EffectType.LOAD_POSITION))

    return _ignored(s)


def _reading(s: Snapshot, event: Event) -> Transition:
    et = event.type
    if et is EventType.SENTENCE_DONE:
        if event.position is None:  # end of book
            nxt = Snapshot(state=ReadingState.IDLE, position=s.position)
            return Transition(nxt, _fx(EffectType.STOP_NARRATION, EffectType.PERSIST))
        return Transition(
            replace(s, position=event.position), (Effect(EffectType.CHECKPOINT, event.position),)
        )
    if et is EventType.SEEK and event.position is not None:
        return Transition(
            replace(s, position=event.position),
            (
                Effect(EffectType.STOP_NARRATION),
                Effect(EffectType.PLAY_NARRATION, event.position),
                Effect(EffectType.CHECKPOINT, event.position),
            ),
        )
    if et is EventType.VAD_SPEECH_START:
        nxt = replace(s, state=ReadingState.USER_SPEAKING, interrupt_point=s.position, ducked=True)
        return Transition(nxt, _fx(EffectType.DUCK_AUDIO))
    if et is EventType.CONTROL_ASK:
        nxt = replace(s, state=ReadingState.USER_SPEAKING, interrupt_point=s.position, ducked=False)
        return Transition(nxt, _fx(EffectType.STOP_NARRATION))
    return _ignored(s)


def _user_speaking(s: Snapshot, event: Event, config: MachineConfig) -> Transition:
    et = event.type
    if et is EventType.INTERRUPT_CONFIRMED:
        if not s.ducked:
            return _ignored(s)
        return Transition(replace(s, ducked=False), _fx(EffectType.STOP_NARRATION))
    if et is EventType.FALSE_INTERRUPTION:
        if s.ducked:
            # Narration never stopped: continue as if nothing happened (no position loss).
            return Transition(
                replace(s, state=ReadingState.READING, interrupt_point=None, ducked=False),
                _fx(EffectType.UNDUCK_AUDIO),
            )
        return Transition(
            replace(s, state=ReadingState.AWAITING_FOLLOWUP), _fx(EffectType.START_FOLLOWUP_TIMER)
        )
    if et is EventType.STT_FINAL:
        return _handle_utterance(s, event, config, narration_ducked=s.ducked, cancel_timer=False)
    return _ignored(s)


def _handle_utterance(
    s: Snapshot, event: Event, config: MachineConfig, *, narration_ducked: bool, cancel_timer: bool
) -> Transition:
    intent = event.intent or Intent.UNCLEAR
    prefix: list[Effect] = []
    if cancel_timer:
        prefix.append(Effect(EffectType.CANCEL_FOLLOWUP_TIMER))

    if narration_ducked and intent in (Intent.ACK, Intent.UNCLEAR):
        # A backchannel ("응") or noise while narration was only ducked: keep reading.
        return Transition(
            replace(s, state=ReadingState.READING, interrupt_point=None, ducked=False),
            (*prefix, Effect(EffectType.UNDUCK_AUDIO)),
        )
    if narration_ducked:
        prefix.append(Effect(EffectType.STOP_NARRATION))
    base = replace(s, ducked=False)

    if intent in QUESTION_INTENTS:
        return Transition(
            replace(base, state=ReadingState.PROCESSING_QUESTION),
            (*prefix, Effect(EffectType.ANSWER_QUESTION)),
        )
    if intent is Intent.PLAYBACK_PAUSE:
        return Transition(
            replace(base, state=ReadingState.PAUSED, interrupt_point=s.resume_position),
            (*prefix, Effect(EffectType.PERSIST)),
        )
    if intent is Intent.PLAYBACK_STOP:
        return Transition(
            Snapshot(state=ReadingState.IDLE, position=s.resume_position),
            (*prefix, Effect(EffectType.PERSIST)),
        )
    if intent in (Intent.ACK, Intent.PLAYBACK_RESUME):
        resumed = _resume(base, config)
        return Transition(resumed.snapshot, (*prefix, *resumed.effects))
    if intent is Intent.INTERRUPT_ONLY:
        return Transition(
            replace(base, state=ReadingState.AWAITING_FOLLOWUP),
            (
                *prefix,
                Effect(EffectType.PLAY_CUE, cue=Cue.LISTENING),
                Effect(EffectType.START_FOLLOWUP_TIMER),
            ),
        )
    # UNCLEAR after narration was already stopped: ask again.
    return Transition(
        replace(base, state=ReadingState.AWAITING_FOLLOWUP),
        (*prefix, Effect(EffectType.PLAY_CUE, cue=Cue.PARDON), Effect(EffectType.START_FOLLOWUP_TIMER)),
    )


def _resume(s: Snapshot, config: MachineConfig) -> Transition:
    if s.resume_position is None:
        return _ignored(s)
    if config.bridge_phrase:
        return Transition(
            replace(s, state=ReadingState.RESUMING, interrupt_point=s.resume_position, ducked=False),
            _fx(EffectType.PLAY_BRIDGE),
        )
    return _start_reading_at_interrupt_point(replace(s, interrupt_point=s.resume_position))


def _start_reading_at_interrupt_point(s: Snapshot) -> Transition:
    target = s.resume_position
    if target is None:
        return _ignored(s)
    nxt = Snapshot(state=ReadingState.READING, position=target)
    return Transition(nxt, (Effect(EffectType.PLAY_NARRATION, target),))
