"""후보 점수 계산 + 최종 선정.

analyzer.py가 매긴 10개 항목 점수를 config.json의 가중치로 결정론적으로 합산해
Shorts Score를 계산하고, 사용자가 지정한 개수만큼 상위 후보를 고른다.

지시서 §5: "AI가 충분히 높은 품질의 후보를 찾지 못하면 개수를 억지로 채우지 않는다" —
min_shorts_score 미만인 후보는 아예 탈락시킨다.

지시서 §6/§8: 최대 길이를 넘는 후보는 뒤쪽 세그먼트부터 잘라 길이를 맞추고(문장 단위로만
자르므로 중간에 말이 끊기지 않는다), 겹치는 후보끼리는 점수가 높은 쪽만 남긴다.
"""

from __future__ import annotations

from typing import Any

from .config import normalized_weights
from .models import CandidateScores, ShortCandidate, Transcript


def compute_shorts_score(scores: CandidateScores, cfg: dict[str, Any], low_educational_value: bool) -> float:
    weights = normalized_weights(cfg["weights"])
    base = sum(
        weights[k] * getattr(scores, k)
        for k in weights
        if hasattr(scores, k)
    )
    penalties_cfg = cfg["penalties"]
    penalty = (
        (scores.redundancy_penalty / 100.0) * penalties_cfg["redundancy_penalty_max"]
        + (scores.context_dependency_penalty / 100.0) * penalties_cfg["context_dependency_penalty_max"]
    )
    if low_educational_value:
        penalty += penalties_cfg["low_educational_value_penalty_max"]

    return max(0.0, min(100.0, base - penalty))


def enforce_max_length(candidate: ShortCandidate, transcript: Transcript, max_length_seconds: int) -> ShortCandidate:
    """후보 길이가 max_length를 넘으면 뒤에서부터 세그먼트를 잘라 맞춘다(문장 단위 보존)."""
    if candidate.duration <= max_length_seconds:
        return candidate

    segs = transcript.slice(candidate.start_index, candidate.end_index)
    if not segs:
        return candidate

    new_end_index = candidate.end_index
    for seg in reversed(segs):
        trial_end_time = seg.end
        if trial_end_time - candidate.start_time <= max_length_seconds:
            new_end_index = seg.index
            break
    else:
        # 첫 세그먼트 하나만으로도 길다면 그것만 남긴다(더 잘라낼 수 없음).
        new_end_index = segs[0].index

    start_t, end_t = transcript.time_range(candidate.start_index, new_end_index)
    candidate.end_index = new_end_index
    candidate.start_time = start_t
    candidate.end_time = end_t
    return candidate


def _overlaps(a: ShortCandidate, b: ShortCandidate) -> bool:
    return a.start_index <= b.end_index and b.start_index <= a.end_index


def dedupe_overlaps(candidates: list[ShortCandidate]) -> list[ShortCandidate]:
    """겹치는 구간끼리는 Shorts Score가 높은 것만 남긴다."""
    ordered = sorted(candidates, key=lambda c: c.shorts_score, reverse=True)
    kept: list[ShortCandidate] = []
    for c in ordered:
        if any(_overlaps(c, k) for k in kept):
            continue
        kept.append(c)
    return kept


def select_final_shorts(
    candidates: list[ShortCandidate],
    transcript: Transcript,
    cfg: dict[str, Any],
    requested_count: int,
    max_length_seconds: int,
) -> list[ShortCandidate]:
    scored: list[ShortCandidate] = []
    for c in candidates:
        c = enforce_max_length(c, transcript, max_length_seconds)
        c.shorts_score = compute_shorts_score(c.scores, cfg, c.low_educational_value)
        scored.append(c)

    min_score = cfg.get("min_shorts_score", 70)
    qualified = [c for c in scored if c.shorts_score >= min_score and not c.low_educational_value]

    deduped = dedupe_overlaps(qualified)
    deduped.sort(key=lambda c: c.shorts_score, reverse=True)

    final = deduped[:requested_count]
    final.sort(key=lambda c: c.start_time)  # 결과는 원본 영상 순서로 보여준다
    return final
