"""TalkSession end to end with fake ports: narrate → user speaks → answer → resume.

This is Phase 6's exit criterion in a test: a question asked over narration produces spoken audio and the
reader ends up back where they were. No LiveKit, no database, no clock — the state machine and the I/O
sequence are what is under test.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

import pytest
from story_core.agent.clauses import ClauseChunker
from story_core.agent.router import IntentRouter
from story_core.audio.pcm import PcmAudio
from story_core.logging import redact
from story_core.providers.base import ProviderUnavailable
from story_core.providers.stt.fake import FakeSTTProvider
from story_core.rag.answering import Answer, AnswerClause, AnswerEvent
from story_core.reading.state_machine import Position, ReadingState
from story_core.realtime.protocol import decode

from agent.ports import SpokenSentence
from agent.session import SessionContext, TalkSession

SAMPLE_RATE = 24_000
FRAME_MS = 20
# A book long enough that narration cannot finish while the test is still feeding the microphone.
SENTENCES = [(f"p{p}", s, f"{p}-{s} 문장입니다.") for p in range(1, 13) for s in range(4)]
BOOK_ORDER = [(pid, sid) for pid, sid, _ in SENTENCES]


def tone(peak: int, ms: int = FRAME_MS) -> bytes:
    samples = SAMPLE_RATE * ms // 1000
    if peak == 0:
        return b"\x00\x00" * samples
    return b"".join(
        int(peak if i % 2 == 0 else -peak).to_bytes(2, "little", signed=True) for i in range(samples)
    )


def audio(ms: int = 200) -> PcmAudio:
    return PcmAudio(tone(4000, ms), SAMPLE_RATE)


@dataclass
class FakeRoom:
    """Records what the listener would hear, and feeds the microphone from a script."""

    sample_rate: int = SAMPLE_RATE
    played: list[PcmAudio] = field(default_factory=list)
    sent: list[dict[str, object]] = field(default_factory=list)
    stops: int = 0
    mic_frames: list[bytes] = field(default_factory=list)
    open: bool = True
    play_s: float = 0.001
    # Shared with FakeSpeech when a test needs the order of synthesis and playback.
    log: list[str] = field(default_factory=list)
    _closed: bool = False

    async def play(self, item: PcmAudio) -> None:
        self.played.append(item)
        # A real room paces playback (its queue blocks when full). Without a pause here the narration loop
        # would read the whole book before the microphone delivers a single frame.
        await asyncio.sleep(self.play_s)
        self.log.append("played")

    async def stop_playing(self) -> None:
        self.stops += 1

    async def send(self, payload: bytes) -> None:
        envelope = decode(payload)
        self.sent.append({"type": envelope.type, **envelope.payload})

    async def microphone(self) -> AsyncIterator[bytes]:
        """Scripted frames, then silence until the test hangs up.

        A real reader keeps the microphone open, so the session keeps running; ending the stream is how a
        disconnect looks, and that cancels whatever the agent was saying.
        """
        for frame in self.mic_frames:
            # Yield control so the session's tasks (narration, answering) get to run between frames.
            await asyncio.sleep(0)
            yield frame
        while self.open:
            await asyncio.sleep(0.001)
            yield tone(0)
        self._closed = True

    def hang_up(self) -> None:
        self.open = False

    @property
    def messages(self) -> list[str]:
        return [str(item["type"]) for item in self.sent]

    def of_type(self, message_type: str) -> list[dict[str, object]]:
        return [item for item in self.sent if item["type"] == message_type]


@dataclass
class FakeNarration:
    """Sentence audio for a short book, ending after the last sentence."""

    calls: list[tuple[str, int]] = field(default_factory=list)
    book: Sequence[tuple[str, int, str]] = tuple(SENTENCES)

    async def sentences_from(
        self, *, paragraph_id: str, sentence_index: int, count: int
    ) -> Sequence[SpokenSentence]:
        self.calls.append((paragraph_id, sentence_index))
        start = next(
            (
                index
                for index, (pid, sid, _) in enumerate(self.book)
                if pid == paragraph_id and sid == sentence_index
            ),
            None,
        )
        if start is None:
            return []
        spoken = []
        for index in range(start, min(start + count, len(self.book))):
            pid, sid, _ = self.book[index]
            following = self.book[index + 1] if index + 1 < len(self.book) else None
            spoken.append(
                SpokenSentence(
                    paragraph_id=pid,
                    sentence_index=sid,
                    audio=audio(),
                    following=Position(following[0], following[1]) if following else None,
                )
            )
        return spoken


@dataclass
class FakeSpeech:
    said: list[str] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)
    fail_with: Exception | None = None
    log: list[str] = field(default_factory=list)

    async def say(self, text: str) -> PcmAudio:
        if self.fail_with:
            raise self.fail_with
        self.said.append(text)
        self.log.append(f"say:{text}")
        return audio(100)

    async def cue(self, name: str) -> PcmAudio | None:
        self.cues.append(name)
        return audio(50)


@dataclass
class Harness:
    session: TalkSession
    room: FakeRoom
    narration: FakeNarration
    speech: FakeSpeech
    stt: FakeSTTProvider
    asked: list[str]
    # One entry per answer stream that was closed before it finished (generation stopped upstream).
    abandoned: list[str]
    task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.session.run())
        await asyncio.sleep(0)

    async def until(self, predicate: Callable[[], bool], *, limit_s: float = 2.0) -> None:
        """Wait for something the session should do, rather than sleeping a guessed duration."""
        deadline = asyncio.get_running_loop().time() + limit_s
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("timed out waiting for the session")
            await asyncio.sleep(0.002)

    async def finish(self) -> None:
        self.room.hang_up()
        if self.task:
            await asyncio.wait_for(self.task, timeout=2.0)


def answer_for(text: str, *, grounded: bool = True) -> Answer:
    return Answer(
        text=text,
        grounded=grounded,
        allowed_seq=10,
        spoiler_mode="NO_SPOILER",  # type: ignore[arg-type]
        citations=[],
        guard_action="pass",
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
    )


def harness(
    *,
    script: Sequence[str] = (),
    mic: Sequence[bytes] = (),
    answer_text: str = "하람은 등대지기예요. 매일 밤 불을 켰어요.",
    ask_error: Exception | None = None,
    speech_error: Exception | None = None,
    clause_delay_s: float = 0.0,
    play_s: float = 0.001,
    book: Sequence[tuple[str, int, str]] = tuple(SENTENCES),
) -> Harness:
    log: list[str] = []
    room = FakeRoom(mic_frames=list(mic), play_s=play_s, log=log)
    narration = FakeNarration(book=book)
    speech = FakeSpeech(fail_with=speech_error, log=log)
    stt = FakeSTTProvider(script)
    asked: list[str] = []
    abandoned: list[str] = []

    async def ask(question: str) -> AsyncIterator[AnswerEvent]:
        # The shape QuestionService.ask_stream produces: guarded clauses, then the recorded answer.
        asked.append(question)
        if ask_error:
            raise ask_error
        chunker = ClauseChunker()
        finished = False
        try:
            for clause in [*chunker.push(answer_text), chunker.flush()]:
                if clause:
                    await asyncio.sleep(clause_delay_s)
                    yield AnswerClause(clause)
            finished = True
            yield answer_for(answer_text)
        finally:
            if not finished:
                abandoned.append(question)

    session = TalkSession(
        SessionContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), Position("p1", 0)),
        room=room,
        narration=narration,
        speech=speech,
        stt=stt,
        router=IntentRouter(None),
        ask=ask,
        followup_timeout_s=0.05,
    )
    return Harness(session, room, narration, speech, stt, asked, abandoned)


def speech_then_silence(*, speech_frames: int = 12, silence_frames: int = 30) -> list[bytes]:
    return [tone(9000)] * speech_frames + [tone(0)] * silence_frames


async def test_narration_starts_at_the_saved_position_and_reports_each_sentence() -> None:
    h = harness()
    await h.start()

    await h.until(lambda: len(h.room.of_type("sentence")) >= 2)
    await h.finish()

    assert h.narration.calls[0] == ("p1", 0)
    spoken = [(item["paragraph_id"], item["sentence_index"]) for item in h.room.of_type("sentence")]
    assert spoken[:2] == [("p1", 0), ("p1", 1)]
    assert h.room.played, "the listener heard nothing"
    assert h.room.messages[0] == "state"


async def test_narration_crosses_paragraph_boundaries() -> None:
    """Regression: "same paragraph, index + 1" after a paragraph end was read as the end of the book."""
    h = harness()
    await h.start()

    await h.until(lambda: len(h.room.of_type("sentence")) >= 10)
    await h.finish()

    spoken = [(item["paragraph_id"], item["sentence_index"]) for item in h.room.of_type("sentence")]
    assert spoken[:10] == BOOK_ORDER[:10]


async def test_the_end_of_the_book_ends_reading_without_cutting_the_last_sentence() -> None:
    short_book = SENTENCES[:3]
    h = harness(book=short_book)
    await h.start()
    await h.until(lambda: bool(h.room.of_type("sentence")))
    stops_while_reading = h.room.stops

    await h.until(lambda: h.session.state is ReadingState.IDLE)
    await h.finish()

    spoken = [(item["paragraph_id"], item["sentence_index"]) for item in h.room.of_type("sentence")]
    assert spoken == BOOK_ORDER[:3]
    # Nothing was cleared from the playout queue: the last sentence is still being heard.
    assert h.room.stops == stops_while_reading


async def test_a_question_over_narration_is_answered_in_audio_and_then_reading_resumes() -> None:
    """Phase 6 exit criterion: ask while listening, hear an answer, end up back in READING."""
    h = harness(script=["하람은 누구야"], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: h.session.state is ReadingState.READING and bool(h.room.of_type("answer.done")))
    await h.finish()

    assert h.asked == ["하람은 누구야"]
    # The answer was spoken clause by clause, first clause first.
    assert h.speech.said[0].startswith("하람은 등대지기예요")
    assert len(h.speech.said) >= 2
    assert [item["text"] for item in h.room.of_type("answer.delta")] == h.speech.said
    # Narration was stopped for the question and started again afterwards.
    assert h.room.stops >= 1
    states = [item["state"] for item in h.room.of_type("state")]
    assert "USER_SPEAKING" in states and "ANSWERING" in states and states[-1] == "READING"


async def test_reading_resumes_from_the_sentence_that_was_interrupted() -> None:
    """Resume accuracy: the reader must not lose or repeat a sentence because they asked something."""
    h = harness(script=["하람은 누구야"], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: h.session.state is ReadingState.USER_SPEAKING)
    interrupted_at = h.session.position
    spoken_before = len(h.room.of_type("sentence"))

    await h.until(lambda: h.session.state is ReadingState.READING and bool(h.room.of_type("answer.done")))
    # Reading really continues afterwards, rather than just reporting the state.
    await h.until(lambda: len(h.room.of_type("sentence")) > spoken_before)
    await h.finish()

    assert interrupted_at is not None
    after = [
        (item["paragraph_id"], item["sentence_index"]) for item in h.room.of_type("sentence")[spoken_before:]
    ]
    # The first sentence after the answer is the one that was interrupted — not the next one (skipped) and
    # not an earlier one (repeated).
    assert after[0] == (interrupted_at.paragraph_id, interrupted_at.sentence_index)


async def test_the_next_clause_is_synthesised_while_the_current_one_plays() -> None:
    """Otherwise every pause between clauses is as long as that clause's synthesis."""
    h = harness(script=["하람은 누구야"], mic=speech_then_silence(), play_s=0.05)
    await h.start()

    await h.until(lambda: bool(h.room.of_type("answer.done")), limit_s=5.0)
    await h.finish()

    first, second = h.speech.said[:2]
    log = h.room.log
    # The second clause was being made before the first had finished playing.
    assert log.index(f"say:{second}") < log.index("played", log.index(f"say:{first}"))


async def test_leaving_mid_answer_stops_the_answer_stream() -> None:
    """The reader hangs up while the model is still writing: generation nobody will hear must stop."""
    h = harness(script=["하람은 누구야"], mic=speech_then_silence(), clause_delay_s=0.2)
    await h.start()

    await h.until(lambda: len(h.room.of_type("answer.delta")) == 1)
    await h.finish()

    assert h.abandoned == ["하람은 누구야"]
    assert not h.room.of_type("answer.done")


async def test_the_answer_is_recorded_with_where_the_reader_was() -> None:
    h = harness(script=["하람은 누구야"], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: bool(h.room.of_type("answer.done")))
    await h.finish()

    assert len(h.session.answers) == 1
    assert h.session.answers[0].grounded is True
    # Timing marks for the trace: speech → transcript → intent → first audio.
    marks = h.session.timings.marks
    for name in ("speech_start", "stt_final", "intent_decided", "answer_first_voice"):
        assert name in marks, name
    assert h.session.timings.since("stt_final", "answer_first_voice") is not None
    # The marks are logged at the end of every job; the log redactor must not hide them.
    assert redact({"latency_ms": marks}) == {"latency_ms": marks}


async def test_a_playback_command_never_reaches_the_question_path() -> None:
    h = harness(script=["멈춰"], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: h.session.state is ReadingState.PAUSED)
    await h.finish()

    assert h.asked == []  # no LLM call, no retrieval
    assert h.speech.said == []


async def test_stop_ends_the_session() -> None:
    h = harness(script=["그만"], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: h.session.state is ReadingState.IDLE)
    await h.finish()

    assert h.asked == []


async def test_a_failed_answer_plays_a_cue_and_waits_instead_of_going_silent() -> None:
    h = harness(
        script=["하람은 누구야"], mic=speech_then_silence(), ask_error=ProviderUnavailable("llm down")
    )
    await h.start()

    await h.until(lambda: "ANSWER_FAILED" in h.speech.cues)
    await h.finish()

    assert h.asked == ["하람은 누구야"]


async def test_unclear_speech_asks_the_reader_to_repeat() -> None:
    h = harness(script=[""], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: "PARDON" in h.speech.cues)
    await h.finish()

    assert h.asked == []


async def test_state_messages_carry_the_position_for_the_app_to_show() -> None:
    h = harness()
    await h.start()

    await h.until(lambda: len(h.room.of_type("sentence")) >= 1)
    await h.finish()

    with_position = [item for item in h.room.of_type("state") if "position" in item]
    assert with_position, "no state message carried a position"
    position = with_position[-1]["position"]
    assert isinstance(position, dict)
    assert str(position["paragraph_id"]).startswith("p")


@pytest.mark.parametrize("utterance", ["잠깐", "응"])
async def test_attention_and_acknowledgement_do_not_start_an_answer(utterance: str) -> None:
    h = harness(script=[utterance], mic=speech_then_silence())
    await h.start()

    await h.until(lambda: h.session.state is not ReadingState.READING)
    await h.finish()

    assert h.asked == []
