"""Types shared by every AI provider (docs/provider-abstraction.md §2, §4).

A provider implementation is responsible for **one request**: no caching, no retries, no metering. Those
live in wrappers (``story_core.providers.resilience``) so the same policy applies to every vendor and the
domain code never depends on a specific one.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    provider: str
    # Model/engine version. Part of every cache key: upgrading the model must not replay old results.
    model: str
    capabilities: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Usage:
    """What one call consumed. Recorded per request for cost attribution (usage_records, Phase 12)."""

    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    audio_ms: int = 0
    images: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            characters=self.characters + other.characters,
            audio_ms=self.audio_ms + other.audio_ms,
            images=self.images + other.images,
        )


class ProviderError(Exception):
    """Base class for every provider failure. ``retryable`` decides whether a wrapper may try again."""

    retryable = False


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    """Connection failure or 5xx."""

    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True

    def __init__(self, message: str = "rate limited", *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderBadRequest(ProviderError):
    """Malformed request or unsupported parameters: retrying sends the same broken request."""


class ProviderAuthError(ProviderError):
    """Credentials rejected. Never retried — it needs an operator, so it is alerted on instead."""


class ProviderContentRejected(ProviderError):
    """Blocked by the provider's safety filter."""
