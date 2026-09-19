"""Audio cache keys (docs/provider-abstraction.md §6).

The requirement's key (book_id, paragraph_id, voice_id, speed, emotion) is extended with the text itself
and the provider/model/voice versions: edited text or an upgraded model must never replay stale audio,
and identical text is reused across books and reprocessing.
"""

import hashlib
import unicodedata

from story_core.providers.tts.base import ProviderInfo, TTSRequest

_SEPARATOR = "\x1f"


def _digest(*parts: str) -> str:
    return hashlib.sha256(_SEPARATOR.join(parts).encode()).hexdigest()


def normalize_for_tts(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def sentence_cache_key(info: ProviderInfo, request: TTSRequest, sample_rate: int) -> str:
    return _digest(
        "sentence",
        info.provider,
        info.model,
        request.voice.key,
        request.language,
        f"{request.speed:.2f}",
        request.emotion or "",
        f"pcm16@{sample_rate}",
        normalize_for_tts(request.text),
    )


def paragraph_cache_key(sentence_keys: list[str], *, audio_format: str) -> str:
    return _digest("paragraph", audio_format, *sentence_keys)


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_tts(text).encode()).hexdigest()


def sentence_storage_key(cache_key: str) -> str:
    return f"audio/sentences/{cache_key[:2]}/{cache_key}.wav"


def paragraph_storage_key(cache_key: str, extension: str) -> str:
    return f"audio/paragraphs/{cache_key[:2]}/{cache_key}.{extension}"
