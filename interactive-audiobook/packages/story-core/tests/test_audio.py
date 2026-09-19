"""Narration audio: PCM, cache keys, rendering, cache reuse (Phase 3 exit criterion), storage signing."""

import shutil
import uuid
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import func, select

from story_core.audio.cache_keys import paragraph_cache_key, sentence_cache_key
from story_core.audio.encoding import FfmpegAacEncoder, WavEncoder
from story_core.audio.pcm import PcmAudio, from_wav, silence, to_wav
from story_core.audio.renderer import AudioUnavailable, ParagraphAudioRenderer
from story_core.ingestion.pipeline import ingest_book
from story_core.models import AudioAsset, AudioKind, Book, BookRights, BookStatus, Paragraph
from story_core.providers.tts.base import ProviderInfo, TTSRequest, TTSRequestRejected, Voice
from story_core.providers.tts.fake import FakeTTSProvider
from story_core.storage.local import LocalFileStorage
from story_core.storage.signing import MediaUrlSigner
from tests.conftest import SAMPLE_TEXT, TODAY, Db, create_book

VOICE = Voice("fake-narrator")


async def ready_book(db: Db, storage: LocalFileStorage, source: bytes = SAMPLE_TEXT) -> uuid.UUID:
    book_id = await create_book(db, storage, source)
    await ingest_book(db.sessionmaker, storage, book_id, today=lambda: TODAY)
    return book_id


async def paragraphs_of(db: Db, book_id: uuid.UUID) -> list[Paragraph]:
    async with db.sessionmaker() as session:
        result = await session.execute(
            select(Paragraph).where(Paragraph.book_id == book_id).order_by(Paragraph.global_seq)
        )
        return list(result.scalars())


# ---------------------------------------------------------------- units


def test_wav_roundtrip_and_duration() -> None:
    audio = PcmAudio(b"\x01\x00" * 24_000, 24_000)
    assert audio.duration_ms == 1000
    assert from_wav(to_wav(audio)) == audio
    assert silence(250, 16_000).duration_ms == 250
    with pytest.raises(ValueError):
        PcmAudio(b"\x00", 24_000)


def test_cache_keys_change_with_everything_that_changes_the_audio() -> None:
    info = ProviderInfo("fake", "m1")
    base = TTSRequest("모모는 원형극장에 살았다.", VOICE)
    key = sentence_cache_key(info, base, 24_000)
    same_text_spacing = TTSRequest("모모는  원형극장에\n살았다.", VOICE)
    assert sentence_cache_key(info, same_text_spacing, 24_000) == key  # whitespace-normalised

    variants = [
        sentence_cache_key(ProviderInfo("fake", "m2"), base, 24_000),  # model upgrade
        sentence_cache_key(info, TTSRequest(base.text, Voice("fake-narrator", "2")), 24_000),  # voice version
        sentence_cache_key(info, TTSRequest(base.text, Voice("other")), 24_000),
        sentence_cache_key(info, TTSRequest(base.text + "!", VOICE), 24_000),  # edited text
        sentence_cache_key(info, TTSRequest(base.text, VOICE, emotion="calm"), 24_000),
        sentence_cache_key(info, base, 16_000),
    ]
    assert len({key, *variants}) == len(variants) + 1
    assert paragraph_cache_key([key], audio_format="wav") != paragraph_cache_key([key], audio_format="aac")


async def test_fake_tts_is_deterministic_and_validates_input() -> None:
    tts = FakeTTSProvider()
    first = await tts.synthesize(TTSRequest("짧은 문장.", VOICE))
    second = await tts.synthesize(TTSRequest("짧은 문장.", VOICE))
    assert first.audio == second.audio and first.audio.duration_ms >= 400
    assert first.characters_billed == len("짧은 문장.")
    chunks = [chunk async for chunk in tts.synthesize_stream(TTSRequest("짧은 문장.", VOICE))]
    assert b"".join(chunks) == first.audio.samples
    with pytest.raises(TTSRequestRejected):
        await tts.synthesize(TTSRequest("   ", VOICE))


def test_media_url_signer() -> None:
    now = [1_000_000.0]
    signer = MediaUrlSigner(secret=b"s" * 32, base_url="https://api.example.com/", clock=lambda: now[0])
    url, expires_at = signer.sign("audio/paragraphs/ab/abc.wav", expires_in_s=60)
    assert url.startswith("https://api.example.com/v1/media/audio/paragraphs/ab/abc.wav?exp=")
    signature = url.split("sig=")[1]
    assert signer.verify("audio/paragraphs/ab/abc.wav", expires_at, signature)
    assert not signer.verify("audio/paragraphs/ab/other.wav", expires_at, signature)  # other object
    assert not signer.verify("audio/paragraphs/ab/abc.wav", expires_at + 3600, signature)  # extended expiry
    now[0] += 61
    assert not signer.verify("audio/paragraphs/ab/abc.wav", expires_at, signature)  # expired
    with pytest.raises(ValueError):
        MediaUrlSigner(secret=b"short", base_url="x")


# ---------------------------------------------------------------- rendering


async def test_render_paragraph_with_exact_sentence_timings(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    paragraph = (await paragraphs_of(db, book_id))[0]  # 3 sentences
    tts = FakeTTSProvider()
    renderer = ParagraphAudioRenderer(db.sessionmaker, storage, tts, WavEncoder())

    asset = await renderer.render(paragraph.id, VOICE)

    assert asset.kind == AudioKind.PARAGRAPH and asset.format == "wav"
    assert [t["sentence_index"] for t in asset.timings or []] == [0, 1, 2]
    timings = asset.timings or []
    assert timings[0]["start_ms"] == 0
    assert all(a["end_ms"] == b["start_ms"] for a, b in pairwise(timings))
    assert timings[-1]["end_ms"] == asset.duration_ms
    audio = from_wav(await storage.get_bytes(asset.storage_key))
    assert audio.duration_ms == asset.duration_ms
    # Cost is attributed to the sentence rows only, so summing the table never double-counts.
    assert asset.characters_billed == 0
    async with db.sessionmaker() as session:
        billed = await session.scalar(
            select(func.coalesce(func.sum(AudioAsset.characters_billed), 0)).where(
                AudioAsset.kind == AudioKind.SENTENCE, AudioAsset.paragraph_id == paragraph.id
            )
        )
    assert billed == sum(len(r.text) for r in tts.calls)


async def test_second_playback_does_not_call_tts_again(db: Db, storage: LocalFileStorage) -> None:
    """Phase 3 exit criterion: the same paragraph played twice synthesises once."""
    book_id = await ready_book(db, storage)
    paragraph = (await paragraphs_of(db, book_id))[1]
    tts = FakeTTSProvider()
    renderer = ParagraphAudioRenderer(db.sessionmaker, storage, tts, WavEncoder())

    first = await renderer.render(paragraph.id, VOICE)
    calls_after_first = len(tts.calls)
    second = await renderer.render(paragraph.id, VOICE)

    assert calls_after_first == 2 and len(tts.calls) == 2
    assert second.id == first.id

    # A different delivery format reuses the cached sentences: new paragraph file, zero TTS calls.
    if shutil.which("ffmpeg"):
        aac = await ParagraphAudioRenderer(db.sessionmaker, storage, tts, FfmpegAacEncoder()).render(
            paragraph.id, VOICE
        )
        assert aac.format == "aac" and aac.id != first.id and len(tts.calls) == 2


async def test_identical_text_is_reused_across_books_and_reprocessing(
    db: Db, storage: LocalFileStorage
) -> None:
    source = "제1장\n\n똑같은 문장이다. 다른 책에도 있다.\n".encode()
    tts = FakeTTSProvider()
    renderer = ParagraphAudioRenderer(db.sessionmaker, storage, tts, WavEncoder())
    book_a = await ready_book(db, storage, source)
    book_b = await ready_book(db, storage, source)

    await renderer.render((await paragraphs_of(db, book_a))[0].id, VOICE)
    await renderer.render((await paragraphs_of(db, book_b))[0].id, VOICE)
    assert len(tts.calls) == 2  # two sentences, synthesised once in total

    async with db.sessionmaker() as session:
        row = await session.get(Book, book_a)
        assert row is not None
        row.status = BookStatus.QUEUED
        await session.commit()
    await ingest_book(db.sessionmaker, storage, book_a, today=lambda: TODAY)  # new paragraph ids
    await renderer.render((await paragraphs_of(db, book_a))[0].id, VOICE)
    assert len(tts.calls) == 2

    async with db.sessionmaker() as session:
        paragraph_assets = await session.scalar(
            select(func.count()).select_from(AudioAsset).where(AudioAsset.kind == AudioKind.PARAGRAPH)
        )
    assert paragraph_assets == 1


async def test_voice_change_renders_new_audio(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    paragraph = (await paragraphs_of(db, book_id))[3]
    tts = FakeTTSProvider()
    renderer = ParagraphAudioRenderer(db.sessionmaker, storage, tts, WavEncoder())
    a = await renderer.render(paragraph.id, Voice("narrator-a"))
    b = await renderer.render(paragraph.id, Voice("narrator-b"))
    assert a.cache_key != b.cache_key and len(tts.calls) == 4


async def test_lookup_reports_missing_and_skips_unlicensed(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    paragraphs = await paragraphs_of(db, book_id)
    renderer = ParagraphAudioRenderer(db.sessionmaker, storage, FakeTTSProvider(), WavEncoder())
    await renderer.render(paragraphs[0].id, VOICE)

    found = await renderer.lookup([paragraphs[0].id, paragraphs[1].id, uuid.uuid4()], VOICE)
    assert found[paragraphs[0].id][1] is not None
    assert found[paragraphs[1].id][1] is None
    assert len(found) == 2

    async with db.sessionmaker() as session:
        rights = await session.get(BookRights, book_id)
        assert rights is not None
        rights.audio_rights = False
        await session.commit()
    assert await renderer.lookup([paragraphs[0].id], VOICE) == {}
    with pytest.raises(AudioUnavailable):
        await renderer.render(paragraphs[1].id, VOICE)


async def test_lookup_only_renderer_matches_worker_keys(db: Db, storage: LocalFileStorage) -> None:
    book_id = await ready_book(db, storage)
    paragraph = (await paragraphs_of(db, book_id))[0]
    worker = ParagraphAudioRenderer(db.sessionmaker, storage, FakeTTSProvider(), WavEncoder())
    api = ParagraphAudioRenderer(db.sessionmaker, storage, FakeTTSProvider(), None, audio_format="wav")
    asset = await worker.render(paragraph.id, VOICE)
    assert api_found_asset(await api.lookup([paragraph.id], VOICE), paragraph.id) == asset.id
    with pytest.raises(RuntimeError, match="lookup-only"):
        await api.render(paragraph.id, VOICE)


def api_found_asset(found: dict, paragraph_id: uuid.UUID) -> uuid.UUID | None:  # type: ignore[type-arg]
    asset = found[paragraph_id][1]
    return asset.id if asset else None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed (runs in the worker image)")
async def test_aac_encoder_produces_seekable_m4a() -> None:
    encoded = await FfmpegAacEncoder().encode(PcmAudio(b"\x10\x00" * 48_000, 24_000))
    assert encoded.extension == "m4a" and encoded.content_type == "audio/mp4"
    assert encoded.data[4:8] == b"ftyp"
    # "+faststart" needs a seekable output (a pipe fails): the moov atom must be near the start so the
    # player can begin and seek while the file is still downloading.
    assert 0 < encoded.data.find(b"moov") < 4096
    assert len(encoded.data) < len(to_wav(PcmAudio(b"\x10\x00" * 48_000, 24_000))) // 2


async def test_local_storage_signed_urls(tmp_path: Path) -> None:
    signer = MediaUrlSigner(secret=b"k" * 32, base_url="http://localhost:8000")
    storage = LocalFileStorage(tmp_path, signer=signer)
    url, expires_at = await storage.signed_get_url("audio/x.wav", expires_in_s=30)
    assert storage.verify_signature("audio/x.wav", expires_at, url.split("sig=")[1])
    unsigned = LocalFileStorage(tmp_path)
    with pytest.raises(Exception, match="signer"):
        await unsigned.signed_get_url("audio/x.wav", expires_in_s=30)
