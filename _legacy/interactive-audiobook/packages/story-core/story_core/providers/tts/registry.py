"""Chooses the TTS implementation from configuration. New providers register here only."""

from story_core.providers.tts.base import TTSProvider
from story_core.providers.tts.fake import FakeTTSProvider

SUPPORTED_TTS_PROVIDERS = ("fake",)


def build_tts_provider(name: str) -> TTSProvider:
    if name == "fake":
        return FakeTTSProvider()
    raise ValueError(f"Unknown TTS provider '{name}'. Supported: {', '.join(SUPPORTED_TTS_PROVIDERS)}")
