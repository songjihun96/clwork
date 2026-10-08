"""Offline embedding provider for development and tests.

This is a **hashing bag-of-character-bigrams** model, not a semantic one: it is deterministic, needs no
account, and — unlike random vectors — produces genuinely useful similarities, so retrieval, RRF and the
spoiler filter can be tested end to end without a vendor. Paraphrases that share no characters will not
match, which is exactly what the real model buys us, so retrieval quality numbers must come from the
real provider (docs/ai-architecture.md §3). Rejected in production settings.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from story_core.providers.base import ProviderInfo, Usage
from story_core.providers.embedding.base import EmbeddingKind, EmbeddingResult

_NOT_WORD = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ぀-ヿ一-鿿]+")


def _tokens(text: str) -> list[str]:
    """Character bigrams plus whole words: bigrams survive Korean particles, words keep names sharp."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = [w for w in _NOT_WORD.split(normalized) if w]
    tokens = list(words)
    for word in words:
        tokens.extend(word[i : i + 2] for i in range(max(len(word) - 1, 1)))
    return tokens


class FakeEmbeddingProvider:
    def __init__(self, *, dimensions: int = 1024, model: str = "hashing-bigram-v1") -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions
        self.info = ProviderInfo(provider="fake", model=model, capabilities=frozenset({"batch"}))
        # Tests assert on what was embedded (batching, cache hits).
        self.calls: list[tuple[EmbeddingKind, tuple[str, ...]]] = []

    def vector(self, text: str) -> list[float]:
        counts = Counter(_tokens(text))
        values = [0.0] * self.dimensions
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            # Sign from a second slice keeps unrelated tokens from piling up in the same direction.
            sign = 1.0 if digest[4] & 1 else -1.0
            values[bucket] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0.0:  # no indexable characters: a fixed unit vector keeps the column non-null
            values[0] = 1.0
            return values
        return [v / norm for v in values]

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind, timeout_s: float) -> EmbeddingResult:
        self.calls.append((kind, tuple(texts)))
        return EmbeddingResult(
            vectors=[self.vector(text) for text in texts],
            usage=Usage(input_tokens=sum(len(t) for t in texts) // 3, characters=sum(len(t) for t in texts)),
        )
