"""Talk-mode end to end against the running stack: narrate → ask aloud → hear the answer → reading resumes.

    python scripts/e2e_talk.py [--api-url http://127.0.0.1:8000]

Prerequisites: ``docker compose --profile realtime up -d`` with a seeded, indexed book, and the agent's
offline STT scripted to hear a question first (``STT_FAKE_SCRIPT=하람은 누구야|...``).

The bot plays the reader. Its microphone runs continuously, as a phone's does, carrying silence except for
one burst of "speech" that the fake STT turns into the scripted question. Everything else is real: the API
mints the token, LiveKit dispatches the story agent, the agent re-authorises the session, narrates from the
database, retrieves with the spoiler window and speaks the answer back over WebRTC.

Checks (exit code 1 if any fails):
* narration arrives as audio and ``sentence`` messages before the reader speaks;
* the reader's speech moves the agent to USER_SPEAKING and then ANSWERING;
* the answer arrives as ``answer.delta`` clauses followed by ``answer.done``, with audio;
* the agent returns to READING and the next ``sentence`` is the one that was interrupted;
* when the reader leaves, the agent leaves too (no narration or answers billed to an empty room).
"""

import argparse
import asyncio
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

from livekit import api, rtc
from measure_roundtrip import PASSWORD, call, wait_for_agent_track
from story_core.realtime.protocol import decode

SAMPLE_RATE = 48_000
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
SPEECH_FRAMES = 15  # 300 ms: comfortably over the fake STT's minimum
SPEECH_AMPLITUDE = 12_000
TONE_HZ = 440
# Narration from the fake TTS is a tone; anything above codec noise counts as "heard".
AUDIBLE = 1_000


@dataclass
class Observed:
    started: float = field(default_factory=time.perf_counter)
    messages: list[tuple[float, str, dict[str, object]]] = field(default_factory=list)
    audible_at: list[float] = field(default_factory=list)

    def of_type(self, message_type: str, *, after: float = 0.0) -> list[tuple[float, dict[str, object]]]:
        return [(at, body) for at, kind, body in self.messages if kind == message_type and at >= after]

    def states(self, *, after: float = 0.0) -> list[tuple[float, str]]:
        return [(at, str(body.get("state"))) for at, body in self.of_type("state", after=after)]

    def first_state(self, state: str, *, after: float) -> float | None:
        return next((at for at, value in self.states(after=after) if value == state), None)


def frame(amplitude: int, *, offset: int = 0) -> rtc.AudioFrame:
    """A 440 Hz tone, or silence.

    Not a square wave at half the sample rate: Opus low-passes and the agent resamples to 24 kHz, and both
    would remove a Nyquist-rate "voice" before the speech detector ever saw it.
    """
    audio = rtc.AudioFrame.create(SAMPLE_RATE, 1, SAMPLES_PER_FRAME)
    if amplitude:
        view = memoryview(audio.data)
        for index in range(len(view)):
            view[index] = int(amplitude * math.sin(2 * math.pi * TONE_HZ * (offset + index) / SAMPLE_RATE))
    return audio


Order = dict[tuple[str, int], int]


def prepare(api_url: str) -> tuple[dict, Order]:
    """Throwaway reader on the first book, plus that book's reading order.

    ``sentence`` messages carry ids, not sequence numbers (the app already has the text), so the order the
    resume check needs comes from the same chapter content the app downloads.
    """
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    access = call(api_url, "/v1/auth/register", {"email": email, "password": PASSWORD})["access_token"]
    books = call(api_url, "/v1/books", token=access)["items"]
    if not books:
        raise SystemExit("no readable book: run scripts/seed_sample_book.py first")
    book_id = books[0]["id"]
    order: Order = {}
    for chapter in call(api_url, f"/v1/books/{book_id}", token=access)["chapters"]:
        content = call(api_url, f"/v1/books/{book_id}/chapters/{chapter['id']}", token=access)
        for paragraph in content["paragraphs"]:
            for index in range(len(paragraph["sentences"])):
                order[(paragraph["id"], index)] = paragraph["first_sentence_seq"] + index
    session = call(api_url, "/v1/reading/sessions", {"book_id": book_id}, token=access)
    grant = call(api_url, "/v1/realtime/token", {"session_id": session["id"]}, token=access)
    print(f"book {book_id[:8]}: {len(order)} sentences")
    return grant, order


async def wait_for(predicate, *, timeout_s: float, what: str) -> None:  # type: ignore[no-untyped-def]
    deadline = time.perf_counter() + timeout_s
    while not predicate():
        if time.perf_counter() > deadline:
            raise TimeoutError(what)
        await asyncio.sleep(0.01)


async def run(api_url: str) -> list[str]:
    grant, order = prepare(api_url)

    def seq(body: dict[str, object] | None) -> int | None:
        if body is None:
            return None
        return order.get((str(body["paragraph_id"]), int(str(body["sentence_index"]))))

    observed = Observed()
    room = rtc.Room()

    @room.on("data_received")
    def on_data(packet: rtc.DataPacket) -> None:
        envelope = decode(packet.data)
        observed.messages.append((time.perf_counter(), envelope.type, dict(envelope.payload)))

    await room.connect(grant["url"], grant["token"])
    print(f"connected room={room.name}")

    source = rtc.AudioSource(SAMPLE_RATE, 1, queue_size_ms=100)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    speak = asyncio.Event()
    spoke_at: list[float] = []

    async def microphone() -> None:
        quiet = frame(0)
        # Consecutive frames continue the same sine, so the burst has no clicks between frames.
        loud = [frame(SPEECH_AMPLITUDE, offset=i * SAMPLES_PER_FRAME) for i in range(SPEECH_FRAMES)]
        while True:
            if speak.is_set():
                speak.clear()
                for burst in loud:
                    await source.capture_frame(burst)
                spoke_at.append(time.perf_counter())
            await source.capture_frame(quiet)

    async def listen() -> None:
        stream = await wait_for_agent_track(room, timeout_s=20.0)
        async for event in stream:
            data = memoryview(event.frame.data)
            if max(abs(int(sample)) for sample in data[::8]) >= AUDIBLE:
                observed.audible_at.append(time.perf_counter())

    tasks = [asyncio.create_task(microphone()), asyncio.create_task(listen())]
    failures: list[str] = []
    try:
        await wait_for(
            lambda: len(observed.of_type("sentence")) >= 2 and bool(observed.audible_at),
            timeout_s=30.0,
            what="narration never started",
        )
        print(f"narrating: {len(observed.of_type('sentence'))} sentences, audio heard")

        speak.set()
        await wait_for(lambda: bool(spoke_at), timeout_s=5.0, what="microphone stalled")
        speech_end = spoke_at[0]
        await wait_for(
            lambda: bool(observed.of_type("answer.done", after=speech_end)),
            timeout_s=30.0,
            what="no answer.done after speaking",
        )
        answer_done = observed.of_type("answer.done", after=speech_end)[0][0]
        await wait_for(
            lambda: observed.first_state("READING", after=answer_done) is not None,
            timeout_s=15.0,
            what="agent did not return to READING",
        )
        resumed_at = observed.first_state("READING", after=answer_done) or 0.0
        await wait_for(
            lambda: bool(observed.of_type("sentence", after=resumed_at)),
            timeout_s=15.0,
            what="no narration after the answer",
        )

        # --- what happened, in order ---
        speaking = observed.first_state("USER_SPEAKING", after=speech_end - 1.0)
        answering = observed.first_state("ANSWERING", after=speech_end - 1.0)
        deltas = observed.of_type("answer.delta", after=speech_end)
        answer_text = "".join(str(body["text"]) for _, body in deltas)
        # Narration stops when the reader speaks, so the first sound after ANSWERING is the answer.
        answer_audio = [at for at in observed.audible_at if answering is not None and at >= answering]
        before = [body for at, body in observed.of_type("sentence") if at < (speaking or speech_end)]
        after = observed.of_type("sentence", after=resumed_at)

        print(f"states: {' > '.join(state for _, state in observed.states())}")
        print(f"answer ({len(deltas)} clauses, {len(answer_text)} chars)")
        if speaking is None:
            failures.append("speech never moved the agent to USER_SPEAKING")
        if answering is None:
            failures.append("agent never entered ANSWERING")
        if not deltas or not answer_text.strip():
            failures.append("answer was empty")
        if not answer_audio:
            failures.append("answer produced no audio")

        # Resume accuracy. The position the agent reported when the reader started talking must be the
        # sentence right after the last one it finished, and narration must pick up exactly there — no
        # sentence skipped, none repeated.
        last_done = before[-1] if before else None
        interrupted = next(
            (body.get("position") for at, body in observed.of_type("state") if at == speaking), None
        )
        first_after = after[0][1]
        print(
            f"resume: last finished seq {seq(last_done)}, "
            f"paused at seq {seq(interrupted) if isinstance(interrupted, dict) else None}, "
            f"resumed at seq {seq(first_after)}"
        )
        if not isinstance(interrupted, dict):
            failures.append("USER_SPEAKING state carried no position")
        elif seq(first_after) != seq(interrupted):
            failures.append("reading did not resume where it was interrupted")
        elif last_done is not None and seq(interrupted) != (seq(last_done) or 0) + 1:
            failures.append("the paused position is not the sentence after the last one finished")

        # --- latency (local stack, fake providers: the pipeline's own overhead) ---
        if deltas:
            print(f"speech end -> first answer clause: {(deltas[0][0] - speech_end) * 1000:.0f} ms")
        if answer_audio:
            print(f"speech end -> first answer audio:  {(answer_audio[0] - speech_end) * 1000:.0f} ms")
        if speaking is not None:
            print(
                f"speech end -> USER_SPEAKING seen:  {(speaking - speech_end) * 1000:.0f} ms "
                "(speech began 300 ms before its end)"
            )
        gaps = [b - a for a, b in zip(observed.audible_at, observed.audible_at[1:], strict=False)]
        if gaps:
            print(
                f"audio frame gap: median {statistics.median(gaps) * 1000:.0f} ms, "
                f"max {max(gaps) * 1000:.0f} ms"
            )
    except TimeoutError as exc:
        failures.append(f"timeout: {exc}")
        print(f"states so far: {[state for _, state in observed.states()]}", file=sys.stderr)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await room.disconnect()

    room_name = str(grant["room"])
    left_after = await agent_left_after(room_name, grant["url"])
    if left_after is None:
        failures.append("agent stayed in the room after the reader left")
    else:
        print(f"reader left -> agent gone: {left_after * 1000:.0f} ms")
    return failures


async def agent_left_after(room_name: str, url: str, timeout_s: float = 15.0) -> float | None:
    """Seconds until the room has no participants, via the server API (local dev key by default)."""
    started = time.perf_counter()
    async with api.LiveKitAPI(
        url.replace("ws://", "http://").replace("wss://", "https://"),
        os.environ.get("LIVEKIT_API_KEY", "devkey"),
        os.environ.get("LIVEKIT_API_SECRET", "secretsecretsecretsecretsecretsecretsecret"),
    ) as server:
        while time.perf_counter() - started < timeout_s:
            listed = await server.room.list_participants(api.ListParticipantsRequest(room=room_name))
            if not listed.participants:
                return time.perf_counter() - started
            await asyncio.sleep(0.25)
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    failures = await run(args.api_url)
    print()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS talk mode end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
