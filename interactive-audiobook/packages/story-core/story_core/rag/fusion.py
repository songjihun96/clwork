"""Reciprocal rank fusion (docs/ai-architecture.md §3.2 step 3).

Vector similarity and keyword weight are not on a comparable scale, so ranks are fused, not scores: each
list contributes ``weight / (k + rank)``. ``k`` damps the top of each list so one source cannot dominate
on its own; 60 is the value from the original RRF paper and the usual default.
"""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass

RRF_K = 60


@dataclass(frozen=True, slots=True)
class Fused[K: Hashable]:
    key: K
    score: float
    # Which sources produced it, with the rank each gave it (1-based) — used for debugging retrieval.
    ranks: tuple[tuple[str, int], ...]


def reciprocal_rank_fusion[K: Hashable](
    ranked: Mapping[str, Sequence[K]], *, k: int = RRF_K, weights: Mapping[str, float] | None = None
) -> list[Fused[K]]:
    scores: dict[K, float] = {}
    provenance: dict[K, list[tuple[str, int]]] = {}
    for source, keys in ranked.items():
        weight = (weights or {}).get(source, 1.0)
        for index, key in enumerate(keys):
            rank = index + 1
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
            provenance.setdefault(key, []).append((source, rank))
    fused = [Fused(key=key, score=score, ranks=tuple(provenance[key])) for key, score in scores.items()]
    # Ties broken by the best rank achieved, so the result is deterministic.
    fused.sort(key=lambda item: (-item.score, min(rank for _, rank in item.ranks)))
    return fused
