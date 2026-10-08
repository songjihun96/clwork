"""What the session needs from the outside world, as narrow interfaces.

The session is the piece that must be right — it decides when to speak, when to stop, and where reading
resumes — so it is written against these ports and tested without LiveKit, without a database and without a
clock. The LiveKit implementations live in ``agent/livekit_room.py``.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from story_core.audio.pcm import PcmAudio
from story_core.reading.state_machine import Position


@dataclass(frozen=True, slots=True)
class SpokenSentence:
    """One sentence of narration, with the audio the room will play."""

    paragraph_id: str
    sentence_index: int
    audio: PcmAudio
    # Where reading continues after this sentence; None after the book's last sentence. The narration
    # source knows the book's order, the session does not: after a paragraph's last sentence, "index + 1"
    # names nothing.
    following: Position | None


class Room(Protocol):
    """The realtime transport, reduced to what the session actually does with it."""

    sample_rate: int

    async def play(self, audio: PcmAudio) -> None:
        """Queue audio for the listener. Returns when the audio has been handed over, not when heard."""
        ...

    async def stop_playing(self) -> None:
        """Drop anything queued but not yet heard — barge-in and PAUSE both need this."""
        ...

    async def send(self, payload: bytes) -> None:
        """One reliable story.v1 message."""
        ...

    def microphone(self) -> AsyncIterator[bytes]:
        """20 ms PCM16 mono frames from the reader, for as long as they are connected."""
        ...


class Narration(Protocol):
    """Sentence audio for the book, cached or synthesised (Phase 3's renderer in production)."""

    async def sentences_from(
        self, *, paragraph_id: str, sentence_index: int, count: int
    ) -> Sequence[SpokenSentence]: ...


class Speech(Protocol):
    """Turns an answer into audio, one clause at a time so the first words come out quickly."""

    async def say(self, text: str) -> PcmAudio: ...

    async def cue(self, name: str) -> PcmAudio | None:
        """Short pre-rendered prompts ("응, 말해줘"), or None when that cue has no audio."""
        ...
