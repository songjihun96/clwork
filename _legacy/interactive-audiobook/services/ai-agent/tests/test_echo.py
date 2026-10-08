"""Echo pipeline: every received frame is republished, and a closed sink ends the loop instead of the job.

The round trip itself is measured against a real LiveKit server (scripts/measure_roundtrip.py); this covers
the frame handling, which is the part that has to survive a reader hanging up mid-sentence.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from livekit import rtc

from agent.echo import EchoStats, echo_frames

SAMPLE_RATE = 48_000
SAMPLES = 480  # 10 ms


def frame(*, peak: int = 0, samples: int = SAMPLES) -> rtc.AudioFrame:
    audio = rtc.AudioFrame.create(SAMPLE_RATE, 1, samples)
    if peak:
        view = memoryview(audio.data)
        view[0] = peak
        view[1] = -peak
    return audio


async def stream(frames: list[rtc.AudioFrame]) -> AsyncIterator[rtc.AudioFrameEvent]:
    for item in frames:
        yield rtc.AudioFrameEvent(item)


@dataclass
class FakeSource:
    captured: list[rtc.AudioFrame]
    fail_after: int | None = None

    async def capture_frame(self, audio: rtc.AudioFrame) -> None:
        if self.fail_after is not None and len(self.captured) >= self.fail_after:
            raise RuntimeError("source closed")
        self.captured.append(audio)


async def test_frames_are_echoed_with_audio_duration_and_peak() -> None:
    source = FakeSource(captured=[])
    frames = [frame(peak=1200), frame(peak=9000), frame()]

    stats = await echo_frames(stream(frames), source, stats=EchoStats())  # type: ignore[arg-type]

    assert len(source.captured) == 3
    assert stats.frames == 3 and stats.samples == 3 * SAMPLES
    assert stats.audio_ms == 30  # 3 x 10 ms
    assert stats.peak == 9000  # the loudest sample, so a test can tell audio from silence
    assert stats.dropped == 0


async def test_a_closed_sink_stops_the_loop_and_is_counted() -> None:
    """The reader hung up: publishing fails, and the job ends cleanly rather than raising."""
    source = FakeSource(captured=[], fail_after=1)

    stats = await echo_frames(stream([frame(peak=100)] * 4), source)  # type: ignore[arg-type]

    assert len(source.captured) == 1
    assert stats.dropped == 1 and stats.frames == 2  # the failing frame was received, then the loop ended


async def test_no_audio_is_not_an_error() -> None:
    stats = await echo_frames(stream([]), FakeSource(captured=[]))  # type: ignore[arg-type]
    assert stats.frames == 0 and stats.audio_ms == 0 and stats.peak == 0


@pytest.mark.parametrize("rate", [16_000, 24_000, 48_000])
async def test_duration_follows_the_incoming_sample_rate(rate: int) -> None:
    """The agent does not resample: 10 ms in must read as 10 ms out at any rate."""
    audio = rtc.AudioFrame.create(rate, 1, rate // 100)
    source = FakeSource(captured=[])

    async def one() -> AsyncIterator[rtc.AudioFrameEvent]:
        yield rtc.AudioFrameEvent(audio)

    stats = await echo_frames(one(), source)  # type: ignore[arg-type]
    assert stats.audio_ms == 10
