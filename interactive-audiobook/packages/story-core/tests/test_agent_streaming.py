"""ClauseChunker and the offline STT stream — the two pieces that decide when the agent starts talking."""

import pytest

from story_core.agent.clauses import FIRST_MIN_CHARS, ClauseChunker, split_clauses
from story_core.providers.stt.base import FRAME_MS, STTEventType
from story_core.providers.stt.fake import FakeSTTProvider
from story_core.providers.stt.registry import build_stt_provider


def stream_text(text: str, *, step: int = 3, **options: int) -> tuple[list[str], str | None]:
    """Feed text the way an LLM does: a few characters at a time."""
    chunker = ClauseChunker(**options)
    clauses: list[str] = []
    for index in range(0, len(text), step):
        clauses.extend(chunker.push(text[index : index + step]))
    return clauses, chunker.flush()


# --------------------------------------------------------------------------- clause chunking


def test_first_clause_is_emitted_as_early_as_a_boundary_allows() -> None:
    """Time-to-first-audio: the opening clause must not wait for the whole answer."""
    clauses, tail = stream_text("하람은 등대지기예요. 매일 밤 불을 켰고 배들을 기다렸어요.")

    assert clauses[0] == "하람은 등대지기예요."
    assert len(clauses[0]) >= FIRST_MIN_CHARS
    # Nothing is lost or duplicated: clauses plus the tail reconstruct the answer.
    spoken = " ".join(clauses + ([tail] if tail else []))
    assert spoken.split() == "하람은 등대지기예요. 매일 밤 불을 켰고 배들을 기다렸어요.".split()


def test_connective_endings_are_clause_boundaries() -> None:
    clauses, tail = stream_text("바람이 불었고 파도가 높았지만 하람은 등대에 남아 있었어요.")

    assert len(clauses) >= 2
    assert clauses[0].endswith("불었고")
    assert all(clause.strip() for clause in clauses)
    assert (tail or clauses[-1]).endswith("있었어요.")


def test_no_boundary_still_bounds_latency() -> None:
    """A model that produces one long run must not keep the user waiting: the cap cuts at a space."""
    text = "그리고 " * 40  # no punctuation, no connective ending
    clauses, tail = stream_text(text, max_chars=60)

    assert clauses, "the cap never fired"
    assert all(len(clause) <= 60 for clause in clauses)
    rebuilt = " ".join(clauses + ([tail] if tail else []))
    assert rebuilt.split() == text.split()  # nothing lost, nothing duplicated


def test_later_clauses_are_allowed_to_be_longer_than_the_first() -> None:
    """The opening clause buys time-to-first-audio; later ones get room for natural intonation."""
    chunker = ClauseChunker(first_min_chars=6, later_min_chars=30)

    first = chunker.push("짧은 답이에요. ")
    assert first == ["짧은 답이에요."]

    # Below the later minimum, a finished sentence waits and is merged with what follows.
    assert chunker.push("네. ") == []
    merged = chunker.push("그리고 뒤 문장은 훨씬 길게 이어지는 설명이라서 나중에 끊어요. ")
    assert merged and merged[0].startswith("네.")
    assert len(merged[0]) > len(first[0])


def test_nothing_is_emitted_for_empty_or_whitespace_deltas() -> None:
    chunker = ClauseChunker()
    assert chunker.push("") == []
    assert chunker.push("   ") == []
    assert chunker.flush() is None
    assert chunker.emitted == 0


def test_flush_returns_the_tail_without_punctuation() -> None:
    chunker = ClauseChunker()
    assert chunker.push("답변이 중간에 끊겼어") == []
    assert chunker.flush() == "답변이 중간에 끊겼어"
    assert chunker.flush() is None  # already drained


def test_split_clauses_matches_the_streaming_result() -> None:
    text = "첫 문장이에요. 두 번째는 조금 더 길고 설명이 이어져요."
    streamed, tail = stream_text(text)
    if tail:
        streamed.append(tail)
    assert list(split_clauses(text)) == streamed


# --------------------------------------------------------------------------- offline STT


def frame(peak: int, *, sample_rate: int = 24_000) -> bytes:
    samples = sample_rate * FRAME_MS // 1000
    if peak == 0:
        return b"\x00\x00" * samples
    body = bytearray()
    for index in range(samples):
        value = peak if index % 2 == 0 else -peak
        body += int(value).to_bytes(2, "little", signed=True)
    return bytes(body)


async def drain(stream: object) -> list[tuple[STTEventType, str]]:
    return [(event.type, event.text) for event in [item async for item in stream.events()]]  # type: ignore[attr-defined]


async def test_speech_start_fires_on_the_first_loud_frame() -> None:
    stt = FakeSTTProvider(["하람은 누구야"])
    stream = stt.stream()

    await stream.push(frame(0))
    assert await drain(stream) == []

    await stream.push(frame(9000))
    events = await drain(stream)
    assert events == [(STTEventType.SPEECH_START, "")]


async def test_partials_then_one_final_per_utterance() -> None:
    stt = FakeSTTProvider(["하람은 왜 등대에 올라갔어"])
    stream = stt.stream()

    for _ in range(40):  # 800 ms of speech
        await stream.push(frame(9000))
    for _ in range(30):  # silence past the hangover
        await stream.push(frame(0))

    events = await drain(stream)
    kinds = [kind for kind, _ in events]
    assert kinds[0] is STTEventType.SPEECH_START
    assert kinds.count(STTEventType.FINAL) == 1
    assert STTEventType.PARTIAL in kinds
    finals = [text for kind, text in events if kind is STTEventType.FINAL]
    assert finals == ["하람은 왜 등대에 올라갔어"]
    # Partials are prefixes of the final, the way a streaming recogniser reveals words.
    partials = [text for kind, text in events if kind is STTEventType.PARTIAL]
    assert all(finals[0].startswith(text) for text in partials)


async def test_a_short_gap_does_not_split_one_utterance() -> None:
    stt = FakeSTTProvider(["첫 질문", "두 번째 질문"])
    stream = stt.stream()

    for _ in range(10):
        await stream.push(frame(9000))
    for _ in range(5):  # 100 ms pause, shorter than the hangover
        await stream.push(frame(0))
    for _ in range(10):
        await stream.push(frame(9000))
    for _ in range(30):
        await stream.push(frame(0))

    finals = [text for kind, text in await drain(stream) if kind is STTEventType.FINAL]
    assert finals == ["첫 질문"]  # still the first utterance
    assert stt.spoken == 1


async def test_two_utterances_consume_the_script_in_order() -> None:
    stt = FakeSTTProvider(["첫 질문", "두 번째 질문"])
    stream = stt.stream()
    finals: list[str] = []

    for _ in range(2):
        for _ in range(12):
            await stream.push(frame(9000))
        for _ in range(30):
            await stream.push(frame(0))
        finals += [text for kind, text in await drain(stream) if kind is STTEventType.FINAL]

    assert finals == ["첫 질문", "두 번째 질문"]


async def test_sound_with_nothing_scripted_yields_an_empty_final() -> None:
    """Noise, not speech: the agent must get a final it can route to UNCLEAR rather than hang."""
    stt = FakeSTTProvider([])
    stream = stt.stream()

    for _ in range(12):
        await stream.push(frame(9000))
    for _ in range(30):
        await stream.push(frame(0))

    events = await drain(stream)
    assert (STTEventType.FINAL, "") in events


async def test_end_flushes_a_final_for_speech_still_in_progress() -> None:
    stt = FakeSTTProvider(["끊긴 질문"])
    stream = stt.stream()
    for _ in range(12):
        await stream.push(frame(9000))

    await stream.end()

    assert [text for kind, text in await drain(stream) if kind is STTEventType.FINAL] == ["끊긴 질문"]


async def test_usage_counts_audio_seconds_and_close_is_recorded() -> None:
    stt = FakeSTTProvider(["질문"])
    stream = stt.stream()
    for _ in range(50):  # 1 s
        await stream.push(frame(0))

    assert stream.usage.audio_ms == 1000
    await stream.aclose()
    assert stt.closed_streams == 1
    await stream.push(frame(9000))  # closed: ignored
    assert stream.usage.audio_ms == 1000


def test_registry_rejects_unknown_providers() -> None:
    assert isinstance(build_stt_provider("fake", script=("응",)), FakeSTTProvider)
    with pytest.raises(ValueError, match="Unknown STT provider"):
        build_stt_provider("whisper-cloud")
