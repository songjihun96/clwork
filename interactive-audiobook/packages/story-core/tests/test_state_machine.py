"""State machine: the conversational reading flow and its safety invariants (docs/realtime.md §3)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from story_core.reading.state_machine import (
    Cue,
    Effect,
    EffectType,
    Event,
    EventType,
    Intent,
    MachineConfig,
    Position,
    ReadingState,
    Snapshot,
    transition,
)

P0 = Position("p1", 0)
P1 = Position("p1", 1)
P2 = Position("p1", 2)
TALKING = {
    ReadingState.USER_SPEAKING,
    ReadingState.PROCESSING_QUESTION,
    ReadingState.ANSWERING,
    ReadingState.AWAITING_FOLLOWUP,
    ReadingState.RESUMING,
}


def run(
    snapshot: Snapshot, *events: Event, config: MachineConfig | None = None
) -> tuple[Snapshot, list[Effect]]:
    effects: list[Effect] = []
    for event in events:
        step = transition(snapshot, event, config)
        assert not step.ignored, f"{event.type} ignored in {snapshot.state}"
        snapshot = step.snapshot
        effects.extend(step.effects)
    return snapshot, effects


def reading_at(position: Position) -> Snapshot:
    snapshot, _ = run(Snapshot(), Event(EventType.START), Event(EventType.READY, position=position))
    return snapshot


def types(effects: list[Effect]) -> list[EffectType]:
    return [e.type for e in effects]


def test_start_and_read_forward() -> None:
    s, fx = run(
        Snapshot(),
        Event(EventType.START),
        Event(EventType.READY, position=P0),
        Event(EventType.SENTENCE_DONE, position=P1),
    )
    assert s.state is ReadingState.READING and s.position == P1
    assert types(fx) == [EffectType.LOAD_POSITION, EffectType.PLAY_NARRATION, EffectType.CHECKPOINT]


def test_product_ux_interrupt_question_ack_resume() -> None:
    """AI 낭독 → "잠깐" → 즉시 멈춤 → "원형극장이 뭐야?" → 답변 → "응" → "그럼 다시 이야기할게" → 같은 문장."""
    s = reading_at(P0)
    s, _ = run(s, Event(EventType.SENTENCE_DONE, position=P1))

    s, fx = run(s, Event(EventType.VAD_SPEECH_START))  # user starts talking mid-sentence P1
    assert s.state is ReadingState.USER_SPEAKING and s.ducked and s.interrupt_point == P1
    assert types(fx) == [EffectType.DUCK_AUDIO]

    s, fx = run(s, Event(EventType.INTERRUPT_CONFIRMED))  # "잠깐" confirmed → narration stops
    assert types(fx) == [EffectType.STOP_NARRATION] and not s.ducked

    s, fx = run(s, Event(EventType.STT_FINAL, intent=Intent.BOOK_QUESTION))
    assert s.state is ReadingState.PROCESSING_QUESTION
    assert types(fx) == [EffectType.ANSWER_QUESTION]

    s, _ = run(s, Event(EventType.ANSWER_FIRST_AUDIO), Event(EventType.ANSWER_DONE))
    assert s.state is ReadingState.AWAITING_FOLLOWUP

    s, fx = run(s, Event(EventType.VAD_SPEECH_START), Event(EventType.STT_FINAL, intent=Intent.ACK))
    assert s.state is ReadingState.RESUMING
    assert EffectType.PLAY_BRIDGE in types(fx)

    s, fx = run(s, Event(EventType.BRIDGE_DONE))
    assert s.state is ReadingState.READING
    assert s.position == P1 and s.interrupt_point is None
    assert fx == [Effect(EffectType.PLAY_NARRATION, P1)]  # the interrupted sentence, from its start


def test_backchannel_while_reading_does_not_stop_narration() -> None:
    s = reading_at(P0)
    s, fx = run(s, Event(EventType.VAD_SPEECH_START), Event(EventType.STT_FINAL, intent=Intent.ACK))
    assert s.state is ReadingState.READING and s.position == P0 and not s.ducked
    assert types(fx) == [EffectType.DUCK_AUDIO, EffectType.UNDUCK_AUDIO]
    assert EffectType.STOP_NARRATION not in types(fx)


def test_false_interruption_restores_volume_without_losing_position() -> None:
    s = reading_at(P2)
    s, fx = run(s, Event(EventType.VAD_SPEECH_START), Event(EventType.FALSE_INTERRUPTION))
    assert s == Snapshot(state=ReadingState.READING, position=P2)
    assert types(fx) == [EffectType.DUCK_AUDIO, EffectType.UNDUCK_AUDIO]


def test_button_ask_stops_immediately_and_timeout_resumes() -> None:
    s = reading_at(P1)
    s, fx = run(s, Event(EventType.CONTROL_ASK))
    assert types(fx) == [EffectType.STOP_NARRATION] and not s.ducked
    s, _ = run(s, Event(EventType.FALSE_INTERRUPTION))  # pressed the button but said nothing
    assert s.state is ReadingState.AWAITING_FOLLOWUP
    s, _ = run(s, Event(EventType.FOLLOWUP_TIMEOUT), Event(EventType.BRIDGE_DONE))
    assert s.state is ReadingState.READING and s.position == P1


def test_question_while_ducked_stops_narration_first() -> None:
    s = reading_at(P0)
    s, fx = run(s, Event(EventType.VAD_SPEECH_START), Event(EventType.STT_FINAL, intent=Intent.GENERAL))
    assert types(fx) == [EffectType.DUCK_AUDIO, EffectType.STOP_NARRATION, EffectType.ANSWER_QUESTION]


def test_interrupt_only_prompts_and_waits() -> None:
    s = reading_at(P0)
    s, fx = run(s, Event(EventType.CONTROL_ASK), Event(EventType.STT_FINAL, intent=Intent.INTERRUPT_ONLY))
    assert s.state is ReadingState.AWAITING_FOLLOWUP
    assert Effect(EffectType.PLAY_CUE, cue=Cue.LISTENING) in fx


def test_unclear_after_stop_asks_again() -> None:
    s = reading_at(P0)
    s, fx = run(s, Event(EventType.CONTROL_ASK), Event(EventType.STT_FINAL, intent=Intent.UNCLEAR))
    assert Effect(EffectType.PLAY_CUE, cue=Cue.PARDON) in fx
    assert s.state is ReadingState.AWAITING_FOLLOWUP


def test_user_can_interrupt_the_answer() -> None:
    s = reading_at(P0)
    s, _ = run(
        s,
        Event(EventType.CONTROL_ASK),
        Event(EventType.STT_FINAL, intent=Intent.BOOK_QUESTION),
        Event(EventType.ANSWER_FIRST_AUDIO),
    )
    s, fx = run(s, Event(EventType.VAD_SPEECH_START), Event(EventType.INTERRUPT_CONFIRMED))
    assert s.state is ReadingState.USER_SPEAKING and s.interrupt_point == P0
    assert types(fx) == [EffectType.DUCK_AUDIO, EffectType.STOP_ANSWER, EffectType.CANCEL_ANSWER]


def test_answer_failure_keeps_reading_position() -> None:
    s = reading_at(P1)
    s, fx = run(
        s,
        Event(EventType.CONTROL_ASK),
        Event(EventType.STT_FINAL, intent=Intent.BOOK_QUESTION),
        Event(EventType.ANSWER_FAILED),
    )
    assert Effect(EffectType.PLAY_CUE, cue=Cue.ANSWER_FAILED) in fx
    s, _ = run(s, Event(EventType.FOLLOWUP_TIMEOUT), Event(EventType.BRIDGE_DONE))
    assert s.position == P1


def test_voice_pause_command_then_resume_in_listen_mode() -> None:
    listen = MachineConfig(bridge_phrase=False)
    s = reading_at(P2)
    s, _ = run(s, Event(EventType.CONTROL_ASK), Event(EventType.STT_FINAL, intent=Intent.PLAYBACK_PAUSE))
    assert s.state is ReadingState.PAUSED and s.interrupt_point == P2
    s, fx = run(s, Event(EventType.CONTROL_RESUME), config=listen)
    assert s.state is ReadingState.READING and fx == [Effect(EffectType.PLAY_NARRATION, P2)]


def test_seek_while_paused_moves_resume_point() -> None:
    s = reading_at(P0)
    s, _ = run(s, Event(EventType.CONTROL_PAUSE), Event(EventType.SEEK, position=P2))
    s, fx = run(s, Event(EventType.CONTROL_RESUME), config=MachineConfig(bridge_phrase=False))
    assert fx == [Effect(EffectType.PLAY_NARRATION, P2)]


def test_end_of_book_goes_idle() -> None:
    s = reading_at(P2)
    s, fx = run(s, Event(EventType.SENTENCE_DONE, position=None))
    assert s.state is ReadingState.IDLE and s.position == P2
    assert EffectType.PERSIST in types(fx)


def test_fatal_error_recovers_to_last_confirmed_sentence() -> None:
    s = reading_at(P1)
    s, _ = run(s, Event(EventType.CONTROL_ASK), Event(EventType.STT_FINAL, intent=Intent.BOOK_QUESTION))
    s, fx = run(s, Event(EventType.FATAL, retryable=True))
    assert s.state is ReadingState.ERROR and s.resume_position == P1
    assert EffectType.STOP_ANSWER in types(fx) and EffectType.PERSIST in types(fx)
    s, _ = run(s, Event(EventType.RETRY), Event(EventType.READY, position=s.resume_position))
    assert s.state is ReadingState.READING and s.position == P1


def test_non_retryable_error_ignores_retry() -> None:
    s = reading_at(P0)
    s, _ = run(s, Event(EventType.FATAL, retryable=False))
    assert transition(s, Event(EventType.RETRY)).ignored


def test_undefined_events_are_ignored_not_raised() -> None:
    s = reading_at(P0)
    step = transition(s, Event(EventType.BRIDGE_DONE))
    assert step.ignored and step.snapshot == s and step.effects == ()
    assert transition(Snapshot(), Event(EventType.CONTROL_PAUSE)).ignored


# ---------------------------------------------------------------- property-based invariants

POSITIONS = st.sampled_from([Position("p1", i) for i in range(3)] + [Position("p2", i) for i in range(2)])
EVENTS = st.one_of(
    st.builds(
        Event,
        type=st.sampled_from(
            [
                t
                for t in EventType
                if t not in (EventType.STT_FINAL, EventType.SEEK, EventType.SENTENCE_DONE, EventType.READY)
            ]
        ),
        retryable=st.booleans(),
    ),
    st.builds(Event, type=st.just(EventType.STT_FINAL), intent=st.sampled_from(list(Intent))),
    st.builds(Event, type=st.sampled_from([EventType.SEEK, EventType.READY]), position=POSITIONS),
    st.builds(Event, type=st.just(EventType.SENTENCE_DONE), position=st.one_of(st.none(), POSITIONS)),
)


@settings(max_examples=400, deadline=None)
@given(events=st.lists(EVENTS, max_size=60), bridge=st.booleans())
def test_invariants_hold_for_any_event_sequence(events: list[Event], bridge: bool) -> None:
    config = MachineConfig(bridge_phrase=bridge)
    snapshot = Snapshot()
    expected_resume: Position | None = None  # the sentence reading must return to

    for event in events:
        before = snapshot
        step = transition(before, event, config)
        after = step.snapshot
        fx = step.effects

        # 1. READING always has a position and no pending interrupt point.
        if after.state is ReadingState.READING:
            assert after.position is not None and after.interrupt_point is None
        # 2. While talking or paused, the resume point is always known.
        if after.state in TALKING or after.state is ReadingState.PAUSED:
            assert after.interrupt_point is not None
        # 3. Audio is only "ducked" while someone may be interrupting.
        if after.ducked:
            assert after.state in (ReadingState.USER_SPEAKING, ReadingState.ANSWERING)
        # 4. Narration only starts when entering/continuing READING, at the snapshot position.
        for effect in fx:
            if effect.type is EffectType.PLAY_NARRATION:
                assert after.state is ReadingState.READING and effect.position == after.position
        # 5. A known resume position is never lost.
        if before.resume_position is not None:
            assert after.resume_position is not None
        # 6. Ignored events change nothing.
        if step.ignored:
            assert after == before and fx == ()

        # 7. Leaving READING captures the sentence being read; re-entering READING returns to exactly it,
        #    unless the user explicitly moved (SEEK) or reading was (re)started from storage (READY).
        if before.state is ReadingState.READING and after.state is not ReadingState.READING:
            expected_resume = before.position
        if event.type is EventType.SEEK and not step.ignored:
            expected_resume = event.position
        if (
            after.state is ReadingState.READING
            and before.state is not ReadingState.READING
            and event.type is not EventType.READY
            and expected_resume is not None
        ):
            assert after.position == expected_resume

        snapshot = after
