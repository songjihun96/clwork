"""The LiveKit implementation of the session's ``Room`` port.

Three details here are the difference between "audio plays" and "the reader can interrupt":

* **queued audio is bounded.** ``AudioSource`` accepts up to ``queue_size_ms`` of audio and then blocks, which
  is the back-pressure the narration loop relies on. Keep it short: everything queued is audio the reader
  must sit through before an interrupt takes effect.
* **stopping means clearing the queue**, not just stopping to feed it — otherwise barge-in has to wait for
  the buffer to drain.
* **the reader leaving ends the microphone.** The SDK's audio stream does not end when the publisher
  disconnects; without watching for it the session would keep narrating (and paying for synthesis and
  answers) to an empty room until the room itself timed out.
* **the microphone is resampled to the STT's rate** in fixed 20 ms frames. The reader's device picks its own
  rate (usually 48 kHz); recognisers want one specific rate, and partial frames confuse them.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable

from livekit import rtc
from livekit.rtc.room import EventTypes
from story_core.audio.pcm import PcmAudio
from story_core.providers.stt.base import FRAME_MS

logger = logging.getLogger("agent")

# Half a second of buffer: enough to ride out scheduling jitter, short enough that an interrupt is felt.
QUEUE_MS = 500
NARRATION_TRACK = "narration"


class LiveKitRoom:
    """Wraps one joined room. Created by the agent entrypoint, never by the session."""

    def __init__(self, room: rtc.Room, *, sample_rate: int, stt_sample_rate: int) -> None:
        self._room = room
        self.sample_rate = sample_rate
        self._stt_sample_rate = stt_sample_rate
        self._source = rtc.AudioSource(sample_rate, 1, queue_size_ms=QUEUE_MS)
        self._track = rtc.LocalAudioTrack.create_audio_track(NARRATION_TRACK, self._source)
        self._published = False

    async def publish(self) -> None:
        if self._published:
            return
        await self._room.local_participant.publish_track(
            self._track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._published = True

    async def play(self, audio: PcmAudio) -> None:
        """Feed PCM16 in 20 ms frames. Blocks once the queue is full, which paces the narration loop."""
        frame_bytes = audio.sample_rate * FRAME_MS // 1000 * 2
        data = audio.samples
        for start in range(0, len(data), frame_bytes):
            chunk = data[start : start + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            frame = rtc.AudioFrame(chunk, audio.sample_rate, 1, len(chunk) // 2)
            await self._source.capture_frame(frame)

    async def stop_playing(self) -> None:
        self._source.clear_queue()

    async def send(self, payload: bytes) -> None:
        await self._room.local_participant.publish_data(payload, reliable=True)

    async def microphone(self) -> AsyncIterator[bytes]:
        """20 ms PCM16 mono frames at the STT's sample rate, until the reader stops publishing or leaves."""
        found = await self._first_audio_track()
        if found is None:
            return
        track, reader = found
        gone = asyncio.Event()

        def on_participant_left(participant: rtc.RemoteParticipant) -> None:
            if participant.identity == reader:
                gone.set()

        def on_unsubscribed(
            unsubscribed: rtc.Track, _pub: rtc.RemoteTrackPublication, _p: rtc.RemoteParticipant
        ) -> None:
            if unsubscribed.sid == track.sid:
                gone.set()

        def on_disconnected(*_: object) -> None:
            gone.set()

        handlers: list[tuple[EventTypes, Callable[..., None]]] = [
            ("participant_disconnected", on_participant_left),
            ("track_unsubscribed", on_unsubscribed),
            ("disconnected", on_disconnected),
        ]
        for event_name, handler in handlers:
            self._room.on(event_name, handler)
        stream = rtc.AudioStream(track)
        frames = aiter(stream)
        left = asyncio.create_task(gone.wait())
        resampler: rtc.AudioResampler | None = None
        buffer = bytearray()
        frame_bytes = self._stt_sample_rate * FRAME_MS // 1000 * 2
        try:
            while True:
                pending = asyncio.ensure_future(anext(frames))
                await asyncio.wait({pending, left}, return_when=asyncio.FIRST_COMPLETED)
                if not pending.done():
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending
                    logger.info("reader_left", extra={"room": self._room.name})
                    return
                try:
                    frame = pending.result().frame
                except StopAsyncIteration:
                    return
                if frame.sample_rate != self._stt_sample_rate:
                    if resampler is None:
                        resampler = rtc.AudioResampler(frame.sample_rate, self._stt_sample_rate)
                    for resampled in resampler.push(frame):
                        buffer += bytes(resampled.data)
                else:
                    buffer += bytes(frame.data)
                while len(buffer) >= frame_bytes:
                    yield bytes(buffer[:frame_bytes])
                    del buffer[:frame_bytes]
        finally:
            left.cancel()
            for event_name, handler in handlers:
                self._room.off(event_name, handler)
            await stream.aclose()

    async def _first_audio_track(self) -> tuple[rtc.Track, str] | None:
        """The reader's microphone and identity, whether published before or after the agent joined."""
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None and publication.kind == rtc.TrackKind.KIND_AUDIO:
                    return publication.track, participant.identity

        found: asyncio.Future[tuple[rtc.Track, str]] = asyncio.get_running_loop().create_future()

        def on_subscribed(
            track: rtc.Track, _pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
        ) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO and not found.done():
                found.set_result((track, participant.identity))

        self._room.on("track_subscribed", on_subscribed)
        try:
            return await asyncio.wait_for(found, timeout=30.0)
        except TimeoutError:
            logger.warning("reader_never_published_audio", extra={"room": self._room.name})
            return None
        finally:
            self._room.off("track_subscribed", on_subscribed)
