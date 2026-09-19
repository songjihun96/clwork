"""TTSProvider interface (docs/provider-abstraction.md).

Every implementation returns 16-bit mono PCM. Caching, retries, timeouts and usage metering live
outside the provider (see story_core.audio.renderer), so an adapter only implements one request.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from story_core.audio.pcm import PcmAudio
from story_core.providers.base import (
    ProviderError,
    ProviderInfo,
    ProviderRateLimited,
    ProviderUnavailable,
)

__all__ = [
    "ProviderInfo",
    "SynthesisResult",
    "TTSError",
    "TTSProvider",
    "TTSRateLimited",
    "TTSRequest",
    "TTSRequestRejected",
    "TTSUnavailable",
    "Voice",
]


@dataclass(frozen=True, slots=True)
class Voice:
    voice_id: str
    # Bump when the underlying voice changes (e.g. a re-trained personal voice).
    version: str = "1"

    @property
    def key(self) -> str:
        return f"{self.voice_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class TTSRequest:
    text: str
    voice: Voice
    language: str = "ko-KR"
    speed: float = 1.0
    emotion: str | None = None


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    audio: PcmAudio
    characters_billed: int


# TTS keeps its own names (they read better at call sites) but shares the provider error hierarchy,
# so one retry/circuit-breaker policy covers every vendor.
class TTSError(ProviderError):
    pass


class TTSRateLimited(TTSError, ProviderRateLimited):
    retryable = True


class TTSUnavailable(TTSError, ProviderUnavailable):
    retryable = True


class TTSRequestRejected(TTSError):
    """Invalid input or content rejected by the provider: retrying will not help."""


class TTSProvider(Protocol):
    info: ProviderInfo
    sample_rate: int

    async def synthesize(self, request: TTSRequest) -> SynthesisResult: ...

    def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """PCM chunks for low-latency answers (Talk mode, Phase 6). Must stop upstream work on cancel."""
        ...
