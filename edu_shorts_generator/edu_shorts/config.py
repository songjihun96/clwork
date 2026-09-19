"""설정 로딩/저장.

지시서 4번 항목: "가중치는 설정 파일에서 변경 가능하도록 만든다" 를 만족시키기 위해
모든 점수 가중치·페널티·기본값을 config.json 하나에 모아두고, GUI의 설정 창에서도
이 파일을 직접 읽고 쓴다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# 지시서 §4 기본 가중치 (합계 100%)
DEFAULT_WEIGHTS: dict[str, float] = {
    "learning_value": 0.25,
    "concept_importance": 0.20,
    "standalone_understanding": 0.15,
    "completeness": 0.15,
    "explanation_quality": 0.10,
    "example_problem_value": 0.05,
    "exam_practical_relevance": 0.05,
    "clarity": 0.05,
}

DEFAULT_PENALTIES: dict[str, float] = {
    # redundancy_penalty(0~100), context_dependency_penalty(0~100) 원점수에
    # 아래 최대치를 곱해 최종 점수에서 차감한다.
    "redundancy_penalty_max": 15.0,
    "context_dependency_penalty_max": 15.0,
    # AI가 low_educational_value=true 로 표시한 후보에 추가로 차감(사실상 탈락시킴).
    "low_educational_value_penalty_max": 50.0,
}

# 지시서 §3: 콘텐츠 유형별 평가 가중 지침 (숫자 가중치가 아니라 프롬프트에 주입되는
# 서술형 지침 — LLM이 문맥에 맞게 판단하도록 유도한다).
DEFAULT_TYPE_GUIDANCE: dict[str, str] = {
    "수학": "문제 풀이 과정, 공식이 성립하는 원리, 사고 과정(왜 그렇게 푸는지)의 비중을 높게 평가하라. 단순 정답 제시보다 풀이 논리를 우선하라.",
    "과학": "핵심 개념, 원리, 실험 과정, 인과관계 설명의 비중을 높게 평가하라.",
    "역사": "핵심 사건, 원인과 결과, 시대적 맥락, 비교·인과관계 설명의 비중을 높게 평가하라.",
    "국어": "글의 핵심 주제, 문학적/언어적 개념, 예시를 통한 이해도의 비중을 높게 평가하라.",
    "영어": "핵심 문법/어휘 개념, 예문을 통한 설명, 실전 활용 가능성의 비중을 높게 평가하라.",
    "사회": "핵심 개념, 사회적 맥락, 사례 비교, 인과관계의 비중을 높게 평가하라.",
    "코딩": "핵심 개념, 코드 동작 원리, 실습 예시, 자주 하는 실수의 비중을 높게 평가하라.",
    "직업교육": "실제 업무에서 바로 활용할 수 있는 지식, 절차, 실무 팁의 비중을 높게 평가하라.",
    "자격증": "시험에 자주 나오는 핵심 개념, 암기 포인트, 실수하기 쉬운 부분의 비중을 높게 평가하라.",
    "실험": "실험 목적, 과정, 결과 해석의 비중을 높게 평가하라.",
    "실습": "실습 절차, 핵심 포인트, 흔한 실수의 비중을 높게 평가하라.",
    "진로/직업 교육": "실제 진로 선택에 도움이 되는 구체적 정보와 조언의 비중을 높게 평가하라.",
    "기타": "핵심 개념과 학습 가치를 중심으로 균형 있게 평가하라.",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "shorts_count_default": 5,
    "max_length_default": 60,
    "min_shorts_score": 70,
    "weights": DEFAULT_WEIGHTS,
    "penalties": DEFAULT_PENALTIES,
    "type_guidance": DEFAULT_TYPE_GUIDANCE,
    "whisper_model": "medium",
    "whisper_language": None,  # None = 자동 감지
    "chunk_minutes": 15,
    "chunk_overlap_seconds": 60,
    "claude_model": "claude-sonnet-5",
    "claude_max_output_tokens": 8000,
    "vertical_style": "blur_pad",  # blur_pad | crop | none
    "subtitle_enabled_default": True,
    "output_dir": "output",
}


def load_config() -> dict[str, Any]:
    """config.json을 읽는다. 없으면 기본값으로 새로 만든다.

    기존 파일에 새 버전에서 추가된 키가 없으면 기본값으로 채워 넣는다(하위 호환).
    """
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    changed = False
    for key, val in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = val
            changed = True
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if sub_key not in cfg[key]:
                    cfg[key][sub_key] = sub_val
                    changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def normalized_weights(weights: dict[str, float]) -> dict[str, float]:
    """가중치 합이 1이 아니어도(사용자가 설정 파일을 손으로 고쳐도) 항상 합=1로 정규화."""
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}
