"""Deterministic offline TTS for development and tests.

Produces an audible, speech-length signal (soft tones, one per syllable-ish group) so the whole
narration path — caching, storage, signed URLs, mobile playback, sentence highlighting — can be
exercised end to end without a provider account. It is not speech.
"""

import asyncio
import hashlib
import math
import sys
from array import array
from collections.abc import AsyncIterator

from story_core.audio.pcm import PcmAudio
from story_core.providers.tts.base import ProviderInfo, SynthesisResult, TTSRequest, TTSRequestRejected

_MS_PER_CHAR = 70
_MIN_MS = 400
_MAX_CHARS = 1000


class FakeTTSProvider:
    info = ProviderInfo(provider="fake", model="fake-tones-v1", capabilities=frozenset({"streaming"}))

    def __init__(self, *, sample_rate: int = 24_000) -> None:
        self.sample_rate = sample_rate
        self.calls: list[TTSRequest] = []

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        text = request.text.strip()
        if not text:
            raise TTSRequestRejected("empty text")
        if len(text) > _MAX_CHARS:
            raise TTSRequestRejected("text too long for one request")
        self.calls.append(request)
        await asyncio.sleep(0)  # behave like an async provider
        return SynthesisResult(audio=self._render(text, request.voice.voice_id), characters_billed=len(text))

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        result = await self.synthesize(request)
        chunk = self.sample_rate // 10 * 2  # 100 ms of PCM16
        for start in range(0, len(result.audio.samples), chunk):
            await asyncio.sleep(0)
            yield result.audio.samples[start : start + chunk]

    def _render(self, text: str, voice_id: str) -> PcmAudio:
        duration_ms = max(_MIN_MS, len(text) * _MS_PER_CHAR)
        total = self.sample_rate * duration_ms // 1000
        seed = int.from_bytes(hashlib.sha256(f"{voice_id}|{text}".encode()).digest()[:4], "big")
        base_hz = 180 + seed % 120
        tone_frames = self.sample_rate * 180 // 1000
        gap_frames = self.sample_rate * 60 // 1000
        period = tone_frames + gap_frames
        samples = array("h", bytes(total * 2))
        two_pi_over_rate = 2 * math.pi / self.sample_rate
        for i in range(total):
            position = i % period
            if position >= tone_frames:
                continue
            envelope = math.sin(math.pi * position / tone_frames)  # no clicks at tone edges
            hz = base_hz * (1 + 0.12 * ((i // period) % 4))
            samples[i] = int(5000 * envelope * math.sin(hz * i * two_pi_over_rate))
        # Short trailing silence, like a natural sentence end.
        samples.extend(array("h", bytes(self.sample_rate * 120 // 1000 * 2)))
        if sys.byteorder == "big":
            samples.byteswap()  # PCM16 is little-endian
        return PcmAudio(samples.tobytes(), self.sample_rate)
