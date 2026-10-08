"""STTProvider interface (docs/realtime.md §5.1).

Streaming, because the agent must react while the user is still talking: ``speech_start`` ducks the
narration, partials let a playback command ("멈춰") act early, and only ``final`` is allowed to trigger an
answer. Frame size and sample-rate conversion belong to the adapter, so the agent always pushes the same
20 ms PCM16 mono frames it gets from LiveKit.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from story_core.providers.base import ProviderInfo, Usage

# What LiveKit hands us and what every adapter must accept.
FRAME_MS = 20


class STTEventType(StrEnum):
    SPEECH_START = "speech_start"
    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class STTEvent:
    type: STTEventType
    text: str = ""
    # Provider confidence for a final, when it reports one. Never used to gate playback commands.
    confidence: float | None = None
    # Milliseconds of audio pushed when this event was produced: the only clock the agent can trust for
    # "when did the user start speaking", because wall time includes network jitter.
    audio_ms: int = 0
    code: str | None = None


class STTStream(Protocol):
    async def push(self, frame: bytes) -> None:
        """One 20 ms PCM16 mono frame."""
        ...

    async def end(self) -> None:
        """No more audio; flush any pending final."""
        ...

    def events(self) -> AsyncIterator[STTEvent]: ...

    async def aclose(self) -> None:
        """Cancellation path: must close the upstream connection immediately (it is billed per second)."""
        ...

    @property
    def usage(self) -> Usage: ...


class STTProvider(Protocol):
    info: ProviderInfo
    sample_rate: int

    def stream(self, *, language: str = "ko-KR") -> STTStream: ...
