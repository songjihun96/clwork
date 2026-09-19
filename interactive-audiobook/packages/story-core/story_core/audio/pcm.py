"""Raw PCM helpers.

Providers are asked for 16-bit little-endian mono PCM so sentence clips can be joined sample-exactly
and sentence timestamps are exact (compressed formats add encoder padding at every join).
"""

import io
import wave
from dataclasses import dataclass

SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1


@dataclass(frozen=True, slots=True)
class PcmAudio:
    samples: bytes
    sample_rate: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if len(self.samples) % SAMPLE_WIDTH_BYTES:
            raise ValueError("PCM16 data must have an even number of bytes")

    @property
    def frame_count(self) -> int:
        return len(self.samples) // (SAMPLE_WIDTH_BYTES * CHANNELS)

    @property
    def duration_ms(self) -> int:
        return round(self.frame_count * 1000 / self.sample_rate)


def silence(duration_ms: int, sample_rate: int) -> PcmAudio:
    frames = round(sample_rate * duration_ms / 1000)
    return PcmAudio(b"\x00" * frames * SAMPLE_WIDTH_BYTES * CHANNELS, sample_rate)


def to_wav(audio: PcmAudio) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(SAMPLE_WIDTH_BYTES)
        writer.setframerate(audio.sample_rate)
        writer.writeframes(audio.samples)
    return buffer.getvalue()


def from_wav(data: bytes) -> PcmAudio:
    with wave.open(io.BytesIO(data), "rb") as reader:
        if reader.getnchannels() != CHANNELS or reader.getsampwidth() != SAMPLE_WIDTH_BYTES:
            raise ValueError("expected 16-bit mono WAV")
        return PcmAudio(reader.readframes(reader.getnframes()), reader.getframerate())
