"""LLMProvider interface (docs/provider-abstraction.md §2).

Requests are typed objects, not option dicts: a key a vendor does not understand must be a type error,
not a silently ignored setting. ``request_tag`` marks what the call was for so cost can be attributed
per feature ("story_answer" vs "intent") rather than per model.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from story_core.providers.base import ProviderInfo, Usage

Role = Literal["system", "user", "assistant"]
# Cost-attribution tags. A new caller adds one here so usage stays groupable.
RequestTag = Literal["story_answer", "intent", "scene_analysis", "query_rewrite", "probe"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: Sequence[ChatMessage]
    max_tokens: int
    request_tag: RequestTag
    temperature: float = 0.3
    stop: Sequence[str] = ()
    # Requires the "json_schema" capability; providers without it must raise ProviderBadRequest.
    json_schema: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LLMChunk:
    delta: str
    finish_reason: str | None = None
    # Only the final chunk carries usage, and only if the provider reports it.
    usage: Usage | None = None


class LLMProvider(Protocol):
    info: ProviderInfo

    async def generate(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse: ...

    def stream(self, request: LLMRequest, *, timeout_s: float) -> AsyncIterator[LLMChunk]:
        """Token stream. On cancellation the implementation must close the upstream connection:
        a provider that keeps generating keeps billing (docs/provider-abstraction.md §5)."""
        ...


async def close_stream(iterator: AsyncIterator[object]) -> None:
    """Release the upstream connection. Generators expose ``aclose``; a plain iterator may not."""
    closer = getattr(iterator, "aclose", None)
    if closer is not None:
        await closer()
