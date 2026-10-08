"""Measure Talk-mode audio round trip: app → LiveKit → agent → LiveKit → app.

    python scripts/measure_roundtrip.py [--api-url http://127.0.0.1:8000] [--rounds 10]

Goes through the real path — the API mints the token (so grants and explicit agent dispatch are exercised),
the echo agent is reached by dispatch, and audio is published over WebRTC. Each round sends 200 ms of
silence and then one loud frame, and measures how long that frame takes to come back.

This is the floor every later latency budget sits on (docs/realtime.md §4.4): barge-in and answer latency
are measured on top of this transport, so it is worth knowing separately.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid

from livekit import rtc

SAMPLE_RATE = 48_000
CHANNELS = 1
FRAME_MS = 10
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
SILENCE_FRAMES = 20  # 200 ms of quiet before each impulse, so echoes cannot overlap
QUEUE_MS = 40
IMPULSE_AMPLITUDE = 20_000
# Well above codec noise on silence, well below the impulse.
DETECT_THRESHOLD = 4_000
PASSWORD = "Qz7#kWpassword"  # noqa: S105 - throwaway account for a local measurement


def call(url: str, path: str, body: dict[str, object] | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    # Local development tool: the URL comes from --api-url, not from untrusted input.
    request = urllib.request.Request(  # noqa: S310
        url.rstrip("/") + path, data=data, method="POST" if data else "GET"
    )
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{path} -> {exc.code}: {exc.read()[:300]!r}") from exc


def prepare_session(api_url: str) -> dict:
    """Throwaway account on the first readable book, so the script needs no fixtures."""
    email = f"rtt-{uuid.uuid4().hex[:10]}@example.com"
    tokens = call(api_url, "/v1/auth/register", {"email": email, "password": PASSWORD})
    access = tokens["access_token"]
    books = call(api_url, "/v1/books", token=access)
    if not books["items"]:
        raise SystemExit("no readable book: run scripts/seed_sample_book.py first")
    book_id = books["items"][0]["id"]
    session = call(api_url, "/v1/reading/sessions", {"book_id": book_id}, token=access)
    grant = call(api_url, "/v1/realtime/token", {"session_id": session["id"]}, token=access)
    return grant


def impulse_frame(amplitude: int) -> rtc.AudioFrame:
    frame = rtc.AudioFrame.create(SAMPLE_RATE, CHANNELS, SAMPLES_PER_FRAME)
    view = memoryview(frame.data)
    # A short burst rather than one sample: Opus would smooth a single click away.
    for index in range(len(view)):
        view[index] = amplitude if index % 2 == 0 else -amplitude
    return frame


def silence_frame() -> rtc.AudioFrame:
    return rtc.AudioFrame.create(SAMPLE_RATE, CHANNELS, SAMPLES_PER_FRAME)


async def wait_for_agent_track(room: rtc.Room, timeout_s: float) -> rtc.AudioStream:
    """The agent joins by dispatch, so the track appears a moment after we connect."""
    found: asyncio.Future[rtc.Track] = asyncio.get_running_loop().create_future()

    def on_subscribed(track: rtc.Track, *_: object) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and not found.done():
            found.set_result(track)

    room.on("track_subscribed", on_subscribed)
    for participant in room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track is not None and publication.kind == rtc.TrackKind.KIND_AUDIO:
                return rtc.AudioStream(publication.track)
    track = await asyncio.wait_for(found, timeout=timeout_s)
    return rtc.AudioStream(track)


async def measure(grant: dict, rounds: int, *, verbose: bool) -> list[float]:
    room = rtc.Room()
    await room.connect(grant["url"], grant["token"])
    print(f"connected room={room.name} identity={room.local_participant.identity}")

    # A small queue: capture_frame() returns as soon as a frame is *queued*, and the default 1 s of
    # buffer would be measured as transport latency that the transport never had.
    source = rtc.AudioSource(SAMPLE_RATE, CHANNELS, queue_size_ms=QUEUE_MS)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    stream = await wait_for_agent_track(room, timeout_s=20.0)
    print(f"agent track subscribed (agent={grant['agent_name']})")
    frames = aiter(stream)

    latencies: list[float] = []
    impulse = impulse_frame(IMPULSE_AMPLITUDE)
    quiet = silence_frame()
    for round_index in range(rounds):
        for _ in range(SILENCE_FRAMES):
            await source.capture_frame(quiet)
        # Start the clock only once our own queue is empty, so what is measured is the round trip.
        # queued_duration is a polled property; the SDK exposes no "queue drained" event to await.
        while source.queued_duration > 0.001:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
        sent_at = time.perf_counter()
        await source.capture_frame(impulse)

        deadline = sent_at + 5.0
        while time.perf_counter() < deadline:
            event = await asyncio.wait_for(anext(frames), timeout=5.0)
            if max(abs(int(sample)) for sample in memoryview(event.frame.data)) >= DETECT_THRESHOLD:
                latency_ms = (time.perf_counter() - sent_at) * 1000
                latencies.append(latency_ms)
                if verbose:
                    print(f"  round {round_index + 1}: {latency_ms:.0f} ms")
                # Drain the rest of this echo so the next round starts clean.
                for _ in range(SILENCE_FRAMES):
                    await asyncio.wait_for(anext(frames), timeout=5.0)
                break
        else:
            print(f"  round {round_index + 1}: no echo within 5 s", file=sys.stderr)

    await room.disconnect()
    return latencies


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    grant = prepare_session(args.api_url)
    print(f"room={grant['room']} url={grant['url']} protocol={grant['protocol']}")
    latencies = await measure(grant, args.rounds, verbose=args.verbose)

    if not latencies:
        print("no round trip completed: is the ai-agent worker running?", file=sys.stderr)
        return 1
    ordered = sorted(latencies)
    p95 = ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)]
    # No em dash or middle dot: this also runs in terminals whose code page is not UTF-8 (cp949).
    print()
    print(
        f"round trip over {len(latencies)}/{args.rounds} rounds: "
        f"min {ordered[0]:.0f} ms | p50 {statistics.median(ordered):.0f} ms | "
        f"p95 {p95:.0f} ms | max {ordered[-1]:.0f} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
