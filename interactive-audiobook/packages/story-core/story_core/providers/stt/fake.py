"""Offline STT for development and tests.

It does not recognise speech. It detects *that* someone is speaking — frame energy over a threshold — and
then plays back scripted utterances in order. That is enough to drive the whole realtime path without an
account: the barge-in trigger, partial-then-final timing, and the agent's reaction are all exercised, and a
bot client that publishes a loud tone gets a known transcript back.

Rejected in production settings: it would "hear" whatever the script says regardless of the audio.
"""

import array
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from story_core.providers.base import ProviderInfo, Usage
from story_core.providers.stt.base import FRAME_MS, STTEvent, STTEventType

DEFAULT_SAMPLE_RATE = 24_000
# Loud enough to be speech rather than room noise or codec artefacts on silence.
SPEECH_THRESHOLD = 2_000
# Hangover so a short gap inside one utterance does not end it.
SILENCE_FRAMES_TO_END = 25  # 500 ms
# Partials arrive while the user is still talking; the last one is repeated as the final.
PARTIAL_EVERY_FRAMES = 10  # 200 ms


@dataclass
class _Utterance:
    text: str
    partials: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, text: str) -> "_Utterance":
        # Word-by-word partials, the way a streaming recogniser reveals a sentence.
        words = text.split()
        return cls(text=text, partials=[" ".join(words[: i + 1]) for i in range(len(words))])


class FakeSTTStream:
    def __init__(self, provider: "FakeSTTProvider", *, language: str) -> None:
        self._provider = provider
        self._language = language
        self._queue: list[STTEvent] = []
        self._pending: list[STTEvent] = []
        self._audio_ms = 0
        self._speaking = False
        self._silence = 0
        self._speech_frames = 0
        self._partial_index = 0
        self._closed = False
        self._usage = Usage()

    @property
    def usage(self) -> Usage:
        return self._usage

    async def push(self, frame: bytes) -> None:
        if self._closed:
            return
        self._audio_ms += FRAME_MS
        self._usage = Usage(audio_ms=self._audio_ms)
        loud = _peak(frame) >= self._provider.threshold

        if loud:
            self._silence = 0
            self._speech_frames += 1
            if not self._speaking:
                self._speaking = True
                self._partial_index = 0
                self._emit(STTEventType.SPEECH_START)
            elif self._speech_frames % PARTIAL_EVERY_FRAMES == 0:
                self._emit_partial()
            return

        if self._speaking:
            self._silence += 1
            if self._silence >= self._provider.silence_frames_to_end:
                self._finish()

    async def end(self) -> None:
        if self._speaking:
            self._finish()
        self._closed = True

    def events(self) -> AsyncIterator[STTEvent]:
        return self._drain()

    async def _drain(self) -> AsyncIterator[STTEvent]:
        # Events are produced by push(), so draining never blocks: the caller interleaves push and read.
        while self._queue:
            yield self._queue.pop(0)

    async def aclose(self) -> None:
        self._closed = True
        self._provider.closed_streams += 1

    # ------------------------------------------------------------------ internals

    def _current(self) -> _Utterance | None:
        script = self._provider.script
        index = self._provider.spoken
        return script[index] if index < len(script) else None

    def _emit(self, event_type: STTEventType, text: str = "") -> None:
        self._queue.append(STTEvent(type=event_type, text=text, audio_ms=self._audio_ms))

    def _emit_partial(self) -> None:
        utterance = self._current()
        if utterance is None or not utterance.partials:
            return
        index = min(self._partial_index, len(utterance.partials) - 1)
        self._emit(STTEventType.PARTIAL, utterance.partials[index])
        self._partial_index += 1

    def _finish(self) -> None:
        self._speaking = False
        self._silence = 0
        self._speech_frames = 0
        utterance = self._current()
        if utterance is None:
            # Nothing scripted left: the recogniser heard sound but no words.
            self._queue.append(
                STTEvent(type=STTEventType.FINAL, text="", confidence=0.0, audio_ms=self._audio_ms)
            )
            return
        self._provider.spoken += 1
        self._queue.append(
            STTEvent(type=STTEventType.FINAL, text=utterance.text, confidence=0.95, audio_ms=self._audio_ms)
        )


def _peak(frame: bytes) -> int:
    if not frame:
        return 0
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    return max((abs(value) for value in samples), default=0)


class FakeSTTProvider:
    """``script`` is consumed in order, one entry per detected utterance."""

    def __init__(
        self,
        script: Sequence[str] = (),
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        threshold: int = SPEECH_THRESHOLD,
        silence_frames_to_end: int = SILENCE_FRAMES_TO_END,
    ) -> None:
        self.script = [_Utterance.of(text) for text in script]
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.silence_frames_to_end = silence_frames_to_end
        self.info = ProviderInfo(
            provider="fake", model="energy-vad-script", capabilities=frozenset({"streaming"})
        )
        self.spoken = 0
        self.closed_streams = 0
        self.streams: list[FakeSTTStream] = []

    def stream(self, *, language: str = "ko-KR") -> FakeSTTStream:
        stream = FakeSTTStream(self, language=language)
        self.streams.append(stream)
        return stream
