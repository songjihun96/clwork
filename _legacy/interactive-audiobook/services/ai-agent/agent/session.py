"""TalkSession: the realtime loop for one reading session.

The shape of this file is the whole design: **the state machine owns the state, this owns the I/O.** Every
user event is turned into a ``ReadingStateMachine`` event, and the transition's effects are executed here.
Nothing decides "we are answering now" by looking at a flag — it comes back from ``transition()``, which is
a pure function with its own test suite (Phase 2).

Two consequences worth stating, because they are easy to get wrong:

* **the LLM never touches playback.** It produces text; effects move the reader. A model that says "다시
  읽어줄게" does not cause a resume, and it cannot skip a sentence.
* **the answer is cancellable at any moment.** Answering runs as a task; an interrupt cancels it, which
  closes the LLM stream and stops the TTS work that has not been spoken yet (docs/provider-abstraction.md
  §5). Recording only what was actually heard is Phase 7 (barge-in); an interrupted answer is not recorded
  yet.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from story_core.agent.intent import PlaybackCommand
from story_core.agent.router import IntentRouter
from story_core.audio.pcm import PcmAudio
from story_core.providers.base import ProviderError
from story_core.providers.llm.base import LLMProvider, close_stream
from story_core.providers.stt.base import STTEventType, STTProvider
from story_core.rag.answering import Answer, AnswerEvent, QuestionRejected
from story_core.reading.state_machine import (
    Cue,
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
from story_core.realtime.protocol import AgentMessage, MessageWriter

from agent.ports import Narration, Room, Speech

logger = logging.getLogger("agent")

# How many sentences of narration to hold in flight. Small: an interrupt must not have to drain a minute
# of queued audio before the reader hears silence.
NARRATION_LOOKAHEAD = 2
# Answer clauses synthesised ahead of playback: enough to hide synthesis time between clauses, few enough
# that an interrupt wastes little.
ANSWER_LOOKAHEAD = 2
# Silence after an answer before the agent resumes by itself.
FOLLOWUP_TIMEOUT_S = 6.0


@dataclass
class Timings:
    """Span marks for one interaction (docs/realtime.md §8). Text is never recorded here."""

    marks: dict[str, int] = field(default_factory=dict)
    _started: float = field(default_factory=time.perf_counter)

    def mark(self, name: str) -> None:
        self.marks.setdefault(name, int((time.perf_counter() - self._started) * 1000))

    def since(self, first: str, last: str) -> int | None:
        if first in self.marks and last in self.marks:
            return self.marks[last] - self.marks[first]
        return None


@dataclass(frozen=True, slots=True)
class SessionContext:
    session_id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    start: Position


# Guarded clauses as the model writes them, then the recorded Answer (QuestionService.ask_stream).
AskQuestion = Callable[[str], AsyncIterator[AnswerEvent]]


class TalkSession:
    """One job, one reader. ``run()`` returns when the reader leaves or the book ends."""

    def __init__(
        self,
        context: SessionContext,
        *,
        room: Room,
        narration: Narration,
        speech: Speech,
        stt: STTProvider,
        router: IntentRouter,
        ask: AskQuestion,
        llm: LLMProvider | None = None,
        followup_timeout_s: float = FOLLOWUP_TIMEOUT_S,
    ) -> None:
        self._context = context
        self._room = room
        self._narration = narration
        self._speech = speech
        self._stt = stt
        self._router = router
        self._ask = ask
        self._llm = llm
        self._followup_timeout_s = followup_timeout_s

        self._snapshot = Snapshot()
        self._writer = MessageWriter()
        self._config = MachineConfig(bridge_phrase=True)
        self._answer_task: asyncio.Task[None] | None = None
        self._followup_task: asyncio.Task[None] | None = None
        self._narration_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        # Diagnostics the E2E script and tests assert on.
        self.timings = Timings()
        self.answers: list[Answer] = []
        self.spoken_sentences: list[Position] = []
        self.ignored_events = 0

    @property
    def state(self) -> ReadingState:
        return self._snapshot.state

    @property
    def position(self) -> Position | None:
        return self._snapshot.position

    # ------------------------------------------------------------------ main loop

    async def run(self) -> None:
        await self._dispatch(Event(EventType.START))
        await self._dispatch(Event(EventType.READY, position=self._context.start))
        try:
            await self._listen()
        finally:
            await self._cancel_answer()
            await self._cancel_followup()
            if self._narration_task:
                self._narration_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._narration_task

    async def _listen(self) -> None:
        """Push microphone frames into STT and turn its events into machine events."""
        stream = self._stt.stream()
        try:
            async for frame in self._room.microphone():
                if self._stopped.is_set():
                    break
                await stream.push(frame)
                async for event in stream.events():
                    if event.type is STTEventType.SPEECH_START:
                        self.timings.mark("speech_start")
                        await self._dispatch(Event(EventType.VAD_SPEECH_START))
                        # Phase 7 adds the duck→confirm two-step; for now speech is taken at face value.
                        await self._dispatch(Event(EventType.INTERRUPT_CONFIRMED))
                    elif event.type is STTEventType.FINAL:
                        self.timings.mark("stt_final")
                        await self._on_transcript(event.text)
        finally:
            await stream.aclose()

    async def _on_transcript(self, text: str) -> None:
        decision = await self._router.route(text, self._snapshot.state)
        self.timings.mark("intent_decided")
        logger.info(
            "intent_decided",
            extra={
                "intent": decision.intent,
                "source": decision.source,
                "state": self._snapshot.state,
                "chars": len(text),  # never the transcript itself (docs/security.md §7)
            },
        )
        if decision.command is not None:
            await self._apply_playback(decision.command)
            return
        await self._dispatch(Event(EventType.STT_FINAL, intent=decision.intent), question=text)

    async def _apply_playback(self, command: PlaybackCommand) -> None:
        if command is PlaybackCommand.PAUSE:
            await self._dispatch(Event(EventType.CONTROL_PAUSE))
        elif command is PlaybackCommand.STOP:
            await self._dispatch(Event(EventType.CONTROL_STOP))
            self._stopped.set()
        elif command is PlaybackCommand.RESUME:
            await self._dispatch(Event(EventType.CONTROL_RESUME))
        else:
            # Seeking and speed are position changes, not state changes; Phase 7 wires the rest.
            await self._dispatch(Event(EventType.CONTROL_RESUME))

    # ------------------------------------------------------------------ machine plumbing

    async def _dispatch(self, event: Event, *, question: str | None = None) -> None:
        result = transition(self._snapshot, event, self._config)
        if result.ignored:
            self.ignored_events += 1
            logger.info("event_ignored", extra={"event": event.type, "state": self._snapshot.state})
            return
        previous = self._snapshot.state
        self._snapshot = result.snapshot
        if self._snapshot.state is not previous:
            await self._send_state()
        for effect in result.effects:
            await self._apply(effect, question=question)

    async def _apply(self, effect: object, *, question: str | None) -> None:
        from story_core.reading.state_machine import Effect  # local: keeps the port list narrow

        assert isinstance(effect, Effect)
        kind = effect.type
        if kind is EffectType.PLAY_NARRATION:
            await self._start_narration(effect.position or self._snapshot.resume_position)
        elif kind in (EffectType.STOP_NARRATION, EffectType.DUCK_AUDIO):
            await self._stop_narration()
        elif kind is EffectType.STOP_ANSWER or kind is EffectType.CANCEL_ANSWER:
            await self._cancel_answer()
            await self._room.stop_playing()
        elif kind is EffectType.ANSWER_QUESTION:
            await self._start_answer(question or "")
        elif kind is EffectType.START_FOLLOWUP_TIMER:
            await self._start_followup_timer()
        elif kind is EffectType.CANCEL_FOLLOWUP_TIMER:
            await self._cancel_followup()
        elif kind is EffectType.PLAY_CUE and effect.cue is not None:
            await self._play_cue(effect.cue)
        elif kind is EffectType.PLAY_BRIDGE:
            await self._play_bridge()
        elif kind is EffectType.REPORT_ERROR:
            await self._send(
                AgentMessage.ERROR,
                {"code": "agent_error", "retryable": self._snapshot.retryable},
            )
        # LOAD_POSITION, CHECKPOINT and PERSIST are handled by the caller's resources (Phase 7 wires
        # Redis checkpoints and the debounced position write).

    # ------------------------------------------------------------------ narration

    async def _start_narration(self, position: Position | None) -> None:
        if position is None:
            return
        await self._stop_narration()
        self._narration_task = asyncio.create_task(self._narrate(position))

    async def _stop_narration(self) -> None:
        task, self._narration_task = self._narration_task, None
        if task is asyncio.current_task():
            # The book ended: narration itself reported it. Nothing is left to cancel, and the last
            # sentence is still playing out of the queue, so it must not be cleared.
            return
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._room.stop_playing()

    async def _narrate(self, position: Position) -> None:
        """Read sentence by sentence.

        ``SENTENCE_DONE`` is raised **per sentence**, not per fetched batch: the machine's position is what a
        crash or an interrupt resumes from, so it must never lag behind what the listener has heard. (The
        remaining correction — audio handed to the room but not yet played out — is the client's
        ``client.playout`` report, wired in Phase 7.)

        Each sentence says where reading continues after it; the session never works that out itself.
        """
        current = position
        while True:
            sentences = await self._narration.sentences_from(
                paragraph_id=current.paragraph_id,
                sentence_index=current.sentence_index,
                count=NARRATION_LOOKAHEAD,
            )
            if not sentences:
                await self._dispatch(Event(EventType.SENTENCE_DONE, position=None))
                return
            for spoken in sentences:
                at = Position(spoken.paragraph_id, spoken.sentence_index)
                await self._room.play(spoken.audio)
                self.spoken_sentences.append(at)
                await self._send(
                    AgentMessage.SENTENCE,
                    {"paragraph_id": at.paragraph_id, "sentence_index": at.sentence_index},
                )
                # None: the book is finished, and the machine ends the session.
                await self._dispatch(Event(EventType.SENTENCE_DONE, position=spoken.following))
                if spoken.following is None or self._snapshot.state is not ReadingState.READING:
                    return
                current = spoken.following

    # ------------------------------------------------------------------ answering

    async def _start_answer(self, question: str) -> None:
        await self._cancel_answer()
        self._answer_task = asyncio.create_task(self._answer(question))

    async def _cancel_answer(self) -> None:
        task, self._answer_task = self._answer_task, None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _answer(self, question: str) -> None:
        try:
            self.timings.mark("answer_start")
            await self._speak_answer(self._ask(question))
            await self._dispatch(Event(EventType.ANSWER_DONE))
        except asyncio.CancelledError:
            # Barge-in: the reader spoke over the answer. Nothing more is spoken, and the machine has
            # already moved on, so no event is raised here.
            raise
        except (QuestionRejected, ProviderError) as exc:
            logger.warning("answer_failed", extra={"error_type": type(exc).__name__})
            await self._dispatch(Event(EventType.ANSWER_FAILED))
        except Exception:
            logger.exception("answer_crashed")
            await self._dispatch(Event(EventType.ANSWER_FAILED))

    async def _speak_answer(self, events: AsyncIterator[AnswerEvent]) -> None:
        """Speak each clause as soon as it is released, while the model is still writing the rest.

        Two tasks: a producer reads the answer stream and synthesises up to ``ANSWER_LOOKAHEAD`` clauses
        ahead; this task plays them. Reading the stream only between clauses would leave every gap between
        clauses as long as that clause's synthesis. Leaving early (cancel, error) closes the stream, which
        stops generation upstream.
        """
        ready: asyncio.Queue[tuple[str, PcmAudio]] = asyncio.Queue(maxsize=ANSWER_LOOKAHEAD)

        async def produce() -> None:
            try:
                async for event in events:
                    if isinstance(event, Answer):
                        self.timings.mark("answer_generated")
                        self.answers.append(event)
                        continue
                    self.timings.mark("answer_first_clause")
                    await ready.put((event.text, await self._speech.say(event.text)))
            finally:
                await close_stream(events)

        producer = asyncio.create_task(produce())
        first = True
        try:
            while True:
                getter = asyncio.ensure_future(ready.get())
                await asyncio.wait({getter, producer}, return_when=asyncio.FIRST_COMPLETED)
                if not getter.done():
                    getter.cancel()
                    if ready.empty():
                        break  # the producer is done and everything it made has been played
                    continue
                text, audio = getter.result()
                if first:
                    self.timings.mark("answer_first_voice")
                    await self._dispatch(Event(EventType.ANSWER_FIRST_AUDIO))
                    first = False
                # Text first: play() returns only once the clause is (nearly) heard, and the app shows the
                # words as they are spoken, not after.
                await self._send(AgentMessage.ANSWER_DELTA, {"text": text})
                await self._room.play(audio)
            producer.result()  # a failure while answering surfaces here, after what was made was played
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer
        await self._send(AgentMessage.ANSWER_DONE, {})

    # ------------------------------------------------------------------ cues, bridge, timers

    async def _play_cue(self, cue: Cue) -> None:
        audio = await self._speech.cue(cue.value)
        if audio is not None:
            await self._room.play(audio)

    async def _play_bridge(self) -> None:
        audio = await self._speech.cue("BRIDGE")
        if audio is not None:
            await self._room.play(audio)
        await self._dispatch(Event(EventType.BRIDGE_DONE))

    async def _start_followup_timer(self) -> None:
        await self._cancel_followup()
        self._followup_task = asyncio.create_task(self._followup_timer())

    async def _cancel_followup(self) -> None:
        task, self._followup_task = self._followup_task, None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _followup_timer(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(self._followup_timeout_s)
            await self._dispatch(Event(EventType.FOLLOWUP_TIMEOUT))

    # ------------------------------------------------------------------ data channel

    async def _send_state(self) -> None:
        position = self._snapshot.position
        payload: dict[str, object] = {"state": self._snapshot.state.value}
        if position is not None:
            payload["position"] = {
                "paragraph_id": position.paragraph_id,
                "sentence_index": position.sentence_index,
            }
        await self._send(AgentMessage.STATE, payload)

    async def _send(self, message: AgentMessage, payload: dict[str, object]) -> None:
        try:
            await self._room.send(self._writer.encode(message, payload))
        except Exception:  # the reader may already be gone; the session ends on its own
            logger.info("data_message_not_sent", extra={"type": message.value})


def intent_of(text: str) -> Intent:
    """Convenience for callers that only need the rule layer (no I/O, no model)."""
    from story_core.agent.intent import classify_by_rule

    decided = classify_by_rule(text, ReadingState.READING)
    return decided.intent if decided else Intent.BOOK_QUESTION
