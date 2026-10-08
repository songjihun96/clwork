"""EmbeddingProvider interface (docs/provider-abstraction.md §2).

``kind`` exists because asymmetric models embed a question and a passage differently (bge-m3 style
instruction prefixes). Getting it wrong silently degrades recall, so it is a required argument.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from story_core.providers.base import ProviderInfo, Usage

EmbeddingKind = Literal["query", "document"]


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage = field(default_factory=Usage)


class EmbeddingProvider(Protocol):
    info: ProviderInfo
    # Must match the width of the embedding column; the application refuses to start if it does not.
    dimensions: int

    async def embed(
        self, texts: Sequence[str], *, kind: EmbeddingKind, timeout_s: float
    ) -> EmbeddingResult: ...
