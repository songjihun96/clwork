"""Echo pipeline: whatever the reader's microphone sends comes straight back.

Phase 5 needs one thing from the agent side: proof that audio makes the full round trip (app → LiveKit →
agent → LiveKit → app) and a measurement of how long that takes, because every later latency budget
(barge-in, answer) is built on top of it. Story logic arrives in Phase 6.

The frame copy is deliberately dumb — no resampling, no buffering beyond one frame — so the measured time
is the transport's, not ours.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from livekit import rtc

logger = logging.getLogger(__name__)

# The agent republishes at whatever rate it receives, so this only sizes the outgoing source.
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_CHANNELS = 1


@dataclass(slots=True)
class EchoStats:
    frames: int = 0
    samples: int = 0
    # Loudest sample seen, so a test can assert that real audio (not silence) went through.
    peak: int = 0
    dropped: int = 0
    _sample_rate: int = field(default=DEFAULT_SAMPLE_RATE, repr=False)

    @property
    def audio_ms(self) -> int:
        return int(self.samples * 1000 / self._sample_rate) if self._sample_rate else 0


async def echo_frames(
    frames: AsyncIterator[rtc.AudioFrameEvent],
    source: rtc.AudioSource,
    *,
    stats: EchoStats | None = None,
) -> EchoStats:
    """Copy every received frame to ``source``. Returns when the incoming stream ends."""
    result = stats or EchoStats()
    async for event in frames:
        frame = event.frame
        result.frames += 1
        result.samples += frame.samples_per_channel
        result._sample_rate = frame.sample_rate
        result.peak = max(result.peak, _peak(frame))
        try:
            await source.capture_frame(frame)
        except Exception:  # a closed source must not kill the job
            result.dropped += 1
            logger.warning("echo_frame_dropped", extra={"frames": result.frames})
            break
    return result


def _peak(frame: rtc.AudioFrame) -> int:
    """Largest absolute sample value in a PCM16 frame."""
    data = frame.data
    peak = 0
    # memoryview of int16 on every platform LiveKit supports.
    for sample in data:
        value = abs(int(sample))
        if value > peak:
            peak = value
    return peak
