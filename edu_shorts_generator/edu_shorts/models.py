"""데이터 모델 정의.

Whisper 전사 결과, AI가 판단한 쇼츠 후보, 최종 렌더링 결과를 표현하는
가벼운 dataclass 모음. 다른 모듈은 전부 이 타입들을 통해 데이터를 주고받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Word:
    """단어 단위 타임스탬프 (Whisper word_timestamps 결과)."""

    start: float
    end: float
    text: str


@dataclass
class TranscriptSegment:
    """Whisper 문장/구간 단위 세그먼트. 전체 영상 기준 전역 인덱스를 가진다."""

    index: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    """전체 영상의 전사 결과."""

    segments: list[TranscriptSegment]
    language: str
    duration: float

    def slice(self, start_index: int, end_index: int) -> list[TranscriptSegment]:
        """[start_index, end_index] 구간(포함)의 세그먼트를 반환."""
        return [s for s in self.segments if start_index <= s.index <= end_index]

    def text_between(self, start_index: int, end_index: int) -> str:
        return " ".join(s.text.strip() for s in self.slice(start_index, end_index))

    def time_range(self, start_index: int, end_index: int) -> tuple[float, float]:
        seg = self.slice(start_index, end_index)
        if not seg:
            return (0.0, 0.0)
        return (seg[0].start, seg[-1].end)


@dataclass
class CandidateScores:
    """지시서 §4의 10개 점수 (전부 0~100)."""

    learning_value: float = 0.0
    concept_importance: float = 0.0
    standalone_understanding: float = 0.0
    completeness: float = 0.0
    explanation_quality: float = 0.0
    example_problem_value: float = 0.0
    exam_practical_relevance: float = 0.0
    clarity: float = 0.0
    redundancy_penalty: float = 0.0  # 0=반복 없음 ~ 100=심한 반복
    context_dependency_penalty: float = 0.0  # 0=독립적 ~ 100=문맥 의존 심함


@dataclass
class ShortCandidate:
    """AI가 제안한 쇼츠 후보 (렌더링 전 단계)."""

    start_index: int
    end_index: int
    start_time: float
    end_time: float
    title: str
    content_type: str  # 예: "수학 / 개념 설명"
    subject: str  # 예: "수학"
    key_concept: str
    learning_objective: str
    reason: str
    keywords: list[str]
    structure_tags: list[str]  # 존재하는 구조: HOOK/EXPLANATION/EXAMPLE/KEY_POINT
    scores: CandidateScores
    low_educational_value: bool = False
    shorts_score: float = 0.0  # selector.py에서 계산해 채움

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class ShortResult:
    """렌더링까지 끝난 최종 쇼츠 1개."""

    index: int
    candidate: ShortCandidate
    output_path: str
    subtitle_path: Optional[str] = None
    actual_duration: float = 0.0
