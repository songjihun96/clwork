"""Chooses the STT implementation from configuration. New providers register here only."""

from story_core.providers.stt.base import STTProvider
from story_core.providers.stt.fake import FakeSTTProvider

SUPPORTED_STT_PROVIDERS = ("fake",)


def build_stt_provider(name: str, *, script: tuple[str, ...] = ()) -> STTProvider:
    if name == "fake":
        # The script is what the fake "hears"; production providers ignore it (and reject this name).
        return FakeSTTProvider(script)
    raise ValueError(f"Unknown STT provider '{name}'. Supported: {', '.join(SUPPORTED_STT_PROVIDERS)}")
