"""Claude API를 이용한 교육적 가치 분석.

이 모듈이 프로그램의 "핵심 두뇌"다. 사용자가 준 지시서의 판단 기준(학습 가치,
핵심 개념성, 독립적 이해 가능성, 설명 완결성/명확성, 예시·문제풀이 가치,
시험/실무 연관성, 오개념 방지, 기억하기 쉬운 핵심 문장 등)과 제외 기준(인사말,
잡담, 광고, 단순 정답만 말하는 부분 등)을 그대로 시스템 프롬프트에 반영하고,
Claude의 tool-use(구조화 출력)로 항상 파싱 가능한 JSON을 받는다.

점수 자체(0~100, 10개 항목)는 Claude가 매기지만, 그 점수들을 최종
Shorts Score로 합산하는 가중치 계산은 이 모듈이 아니라 selector.py가
config.json 값을 기준으로 결정론적으로 계산한다 — 그래야 사용자가 코드를
건드리지 않고 config.json만 바꿔서 평가 기준 가중치를 조정할 수 있다.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from .models import CandidateScores, ShortCandidate, Transcript

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str], None]]

SCORE_KEYS = [
    "learning_value",
    "concept_importance",
    "standalone_understanding",
    "completeness",
    "explanation_quality",
    "example_problem_value",
    "exam_practical_relevance",
    "clarity",
    "redundancy_penalty",
    "context_dependency_penalty",
]

CONTENT_TYPE_TOOL = {
    "name": "submit_content_type",
    "description": "영상 전체를 훑어보고 교육 콘텐츠 유형을 판단해 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "과목/분야. 예: 수학, 과학, 역사, 국어, 영어, 사회, 코딩, 직업교육, 자격증, 진로/직업 교육, 기타",
            },
            "content_type": {
                "type": "string",
                "description": "콘텐츠 형식. 예: 개념 설명, 문제 풀이, 실험, 실습, 강의, 특강",
            },
            "summary": {
                "type": "string",
                "description": "영상 전체 내용을 1~2문장으로 요약",
            },
        },
        "required": ["subject", "content_type", "summary"],
    },
}


def _candidate_properties() -> dict[str, Any]:
    score_props = {
        k: {"type": "number", "description": "0~100 점수"} for k in SCORE_KEYS
    }
    return {
        "start_index": {"type": "integer", "description": "이 후보의 시작 세그먼트 번호(제공된 [n] 태그)"},
        "end_index": {"type": "integer", "description": "이 후보의 끝 세그먼트 번호(제공된 [n] 태그, 포함)"},
        "title": {"type": "string", "description": "학생의 호기심을 끄는 짧은 제목(원본 내용 기반, 과장/낚시 금지)"},
        "subject": {"type": "string"},
        "content_type": {"type": "string", "description": "예: '수학 / 개념 설명', '역사 / 사건 설명'"},
        "key_concept": {"type": "string", "description": "이 구간이 다루는 핵심 학습 개념"},
        "learning_objective": {"type": "string", "description": "학생이 이 쇼츠를 보고 얻어야 할 학습 목표"},
        "reason": {"type": "string", "description": "이 구간을 쇼츠로 선정한 이유 (교육적 가치 관점)"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "포함된 주요 키워드 3~6개"},
        "structure_tags": {
            "type": "array",
            "items": {"type": "string", "enum": ["HOOK", "EXPLANATION", "EXAMPLE", "KEY_POINT"]},
            "description": "이 구간에 실제로 존재하는 학습 구조 단계(있는 것만)",
        },
        "scores": {
            "type": "object",
            "properties": score_props,
            "required": SCORE_KEYS,
            "description": "10개 평가 항목 점수(0~100). redundancy_penalty/context_dependency_penalty는 '문제가 클수록' 높은 점수.",
        },
        "low_educational_value": {
            "type": "boolean",
            "description": "인사/잡담/광고/출석 등 교육적 가치가 거의 없는 구간이면 true",
        },
    }


def _candidates_tool() -> dict[str, Any]:
    return {
        "name": "submit_candidates",
        "description": "이 구간에서 찾은 교육 쇼츠 후보를 제출한다. 기준을 만족하는 후보가 없으면 빈 배열을 제출해도 된다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": _candidate_properties(),
                        "required": [
                            "start_index",
                            "end_index",
                            "title",
                            "subject",
                            "content_type",
                            "key_concept",
                            "learning_objective",
                            "reason",
                            "keywords",
                            "structure_tags",
                            "scores",
                            "low_educational_value",
                        ],
                    },
                }
            },
            "required": ["candidates"],
        },
    }


SYSTEM_PROMPT = """당신은 교육 콘텐츠 전문 편집자다. 목표는 "조회수가 많이 나올 것 같은 장면"을
찾는 것이 아니라 "학생에게 학습 가치가 높은 구간"을 찾는 것이다.

판단 우선순위(위에서부터 우선): 교육적 가치 > 핵심 개념 > 이해 가능성 > 내용 완결성 >
설명 품질 > 예시/문제풀이 가치 > 시험/실무 활용성 > 흥미도. 흥미도는 보조 요소일 뿐이다.

각 후보는 다음을 만족해야 한다(가능한 한):
1) 학습 가치: 새로운 개념/지식을 이해하거나 기존 지식을 보완·확장할 수 있는가.
2) 핵심 개념성: 주변적 설명이 아니라 과목의 핵심 개념을 다루는가.
3) 독립적 이해 가능성: 영상 전체를 안 봐도 이 구간만으로 이해되는가. 앞뒤 문맥이 과도하게 필요하지 않은가.
4) 설명의 완결성: 가능하면 [질문/문제 제기 → 개념 설명 → 예시/풀이 → 핵심 결론] 구조. 4단계를 모두 갖출 필요는 없지만,
   짧은 시간 안에 하나의 학습 내용이 완결되는 구간을 우선한다.
5) 설명의 명확성: 강사 설명이 명확하고 불필요한 말이 적은가.
6) 예시/사례 가치: 실제 사례나 반례로 개념을 쉽게 이해시키는가.
7) 문제 풀이 가치: 문제 풀이가 있다면 "정답만" 말하는 부분보다 문제 제시→풀이 과정→핵심 공식→사고 과정→정답 도출이
   드러나는 부분을 우선한다.
8) 시험/평가 연관성: 핵심 개념, 자주 혼동하는 개념, 암기 포인트, 공식, 정의, 비교, 차이점, 실수하기 쉬운 부분을 우선한다.
9) 오개념 방지 가치: "많이들 이렇게 알고 있는데 사실은 다릅니다" 류의, 흔한 오해를 바로잡는 설명을 높게 평가한다.
10) 기억하기 쉬운 핵심 문장: 학생이 짧게 보고 기억할 수 있는 핵심 문장/정리가 있는가.

다음은 낮은 우선순위로 두거나 제외한다: 단순 인사, 수업 시작/종료, 출석 확인, 광고, 강사의 개인적 잡담,
지나치게 긴 서론, 반복적인 설명, 문장이 중간에 끊기는 부분, 앞뒤 문맥 없이는 이해 불가한 부분,
단순히 정답만 말하는 부분, 학습 가치가 거의 없는 장면. 재미있어도 교육적 가치가 낮으면 우선순위를 낮춘다.

절대 규칙:
- 원본 영상에 없는 사실, 설명, 대사를 만들어내지 않는다. 오직 실제로 주어진 대본(타임스탬프가 붙은 문장들)에
  근거해서만 후보를 제안한다.
- 후보의 start_index/end_index는 반드시 제공된 [n] 태그 중에서 골라야 하며, 그 사이의 시간 길이가
  사용자가 지정한 최대 길이(max_length_seconds)를 넘지 않아야 한다. 각 줄 앞에 표시된 시각(mm:ss)을 보고
  직접 합산해서 확인하라.
- 자막처럼 문장이 뚝 끊기는 지점이 아니라, 자연스러운 문장/설명이 끝나는 지점을 끝 경계로 선택하라.
- 낚시성 제목이나 자극적 편집을 하지 않는다. 제목은 원본 내용을 정확히 반영해야 한다."""


LENGTH_GUIDANCE = {
    30: "최대 길이가 짧다(약 30초). 하나의 핵심 개념이나 핵심 문장 중심의 후보를 찾아라.",
    60: "최대 길이가 약 60초다. 개념 설명 + (가능하면) 예시/결론까지 포함하는 후보를 찾아라.",
    90: "최대 길이가 약 90초다. 개념 + 설명 + 예시 + 정리가 포함된 후보를 찾아라.",
    120: "최대 길이가 약 120초다. 짧은 강의 형태로 완결된 학습 콘텐츠(개념+설명+예시+정리)를 찾아라.",
}


def _length_guidance(max_length_seconds: int) -> str:
    closest = min(LENGTH_GUIDANCE.keys(), key=lambda k: abs(k - max_length_seconds))
    base = LENGTH_GUIDANCE[closest]
    return f"{base} (설정된 최대 길이를 절대 넘기지 마라. 억지로 채우지 말고, 그 안에서 가장 완성도 높은 학습 단위를 골라라.)"


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class AnthropicNotConfigured(RuntimeError):
    pass


def _get_client():
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic 패키지가 설치되어 있지 않습니다. `pip install -r requirements.txt` 를 실행하세요."
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        from . import secrets as secrets_mod

        api_key = secrets_mod.get_api_key()
    if not api_key:
        raise AnthropicNotConfigured(
            "Anthropic API 키가 설정되지 않았습니다. 설정 창에서 API 키를 입력하세요."
        )
    return anthropic.Anthropic(api_key=api_key)


def detect_content_type(transcript: Transcript, model: str, progress: ProgressCallback = None) -> dict[str, str]:
    """영상 앞/중간/뒤 일부를 보고 과목·콘텐츠 유형을 판단한다 (지시서 §3)."""
    if progress:
        progress("콘텐츠 유형 자동 판단 중...")

    segs = transcript.segments
    if not segs:
        return {"subject": "기타", "content_type": "기타", "summary": ""}

    def sample(seg_list):
        return " ".join(s.text.strip() for s in seg_list)

    n = len(segs)
    head = sample(segs[: min(60, n)])
    mid_start = max(0, n // 2 - 30)
    mid = sample(segs[mid_start: mid_start + 60])
    tail = sample(segs[max(0, n - 60):])

    prompt = (
        "다음은 한 교육 영상 대본의 앞부분/중간부분/뒷부분 발췌다. 이 영상의 과목(subject)과 "
        "콘텐츠 형식(content_type)을 판단해서 제출하라.\n\n"
        f"[앞부분]\n{head}\n\n[중간부분]\n{mid}\n\n[뒷부분]\n{tail}"
    )

    client = _get_client()
    resp = client.messages.create(
        model=model,
        max_tokens=500,
        system="당신은 교육 콘텐츠 분류 전문가다.",
        tools=[CONTENT_TYPE_TOOL],
        tool_choice={"type": "tool", "name": "submit_content_type"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_content_type":
            return block.input
    return {"subject": "기타", "content_type": "기타", "summary": ""}


def _build_chunk_text(transcript: Transcript, start_idx: int, end_idx: int) -> str:
    lines = []
    for seg in transcript.slice(start_idx, end_idx):
        lines.append(f"[{seg.index}] {_fmt_ts(seg.start)}-{_fmt_ts(seg.end)} {seg.text.strip()}")
    return "\n".join(lines)


def iter_chunks(transcript: Transcript, chunk_minutes: float, overlap_seconds: float):
    """시간 기준으로 세그먼트를 청크로 나눈다 (겹침 포함, 전역 인덱스는 그대로 유지)."""
    segs = transcript.segments
    if not segs:
        return
    chunk_seconds = chunk_minutes * 60
    n = len(segs)
    i = 0
    while i < n:
        chunk_start_time = segs[i].start
        j = i
        while j < n and segs[j].start - chunk_start_time < chunk_seconds:
            j += 1
        end_i = min(j, n) - 1
        yield segs[i].index, segs[end_i].index

        if j >= n:
            break
        # 다음 청크 시작점: 겹침을 위해 살짝 앞에서 시작
        overlap_target = segs[j].start - overlap_seconds
        k = j
        while k > i and segs[k - 1].start > overlap_target:
            k -= 1
        i = max(k, i + 1)


def analyze_chunk(
    transcript: Transcript,
    start_idx: int,
    end_idx: int,
    content_type_info: dict[str, str],
    type_guidance: str,
    max_length_seconds: int,
    model: str,
) -> list[ShortCandidate]:
    chunk_text = _build_chunk_text(transcript, start_idx, end_idx)
    if not chunk_text.strip():
        return []

    user_prompt = (
        f"[콘텐츠 유형 정보]\n과목: {content_type_info.get('subject')}\n"
        f"형식: {content_type_info.get('content_type')}\n"
        f"유형별 평가 지침: {type_guidance}\n\n"
        f"[길이 지침]\n{_length_guidance(max_length_seconds)}\n"
        f"max_length_seconds = {max_length_seconds}\n\n"
        "[대본 (형식: [세그먼트번호] 시작-끝 텍스트)]\n"
        f"{chunk_text}\n\n"
        "이 구간 안에서 교육 쇼츠로 만들 만한 후보를 0개 이상 찾아 submit_candidates 도구로 제출하라. "
        "이 구간에 좋은 후보가 없으면 candidates를 빈 배열로 제출해도 된다. "
        "하나의 후보가 여러 세그먼트에 걸쳐도 되지만, 전체 길이가 max_length_seconds를 넘지 않게 하라."
    )

    client = _get_client()
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[_candidates_tool()],
        tool_choice={"type": "tool", "name": "submit_candidates"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    candidates: list[ShortCandidate] = []
    for block in resp.content:
        if block.type != "tool_use" or block.name != "submit_candidates":
            continue
        for c in block.input.get("candidates", []):
            try:
                s_idx = int(c["start_index"])
                e_idx = int(c["end_index"])
                if e_idx < s_idx:
                    s_idx, e_idx = e_idx, s_idx
                s_idx = max(s_idx, transcript.segments[0].index)
                e_idx = min(e_idx, transcript.segments[-1].index)
                start_t, end_t = transcript.time_range(s_idx, e_idx)
                scores_raw = c.get("scores", {})
                scores = CandidateScores(**{k: float(scores_raw.get(k, 0.0)) for k in SCORE_KEYS})
                candidates.append(
                    ShortCandidate(
                        start_index=s_idx,
                        end_index=e_idx,
                        start_time=start_t,
                        end_time=end_t,
                        title=c.get("title", "").strip() or "(제목 없음)",
                        content_type=c.get("content_type", content_type_info.get("content_type", "")),
                        subject=c.get("subject", content_type_info.get("subject", "")),
                        key_concept=c.get("key_concept", ""),
                        learning_objective=c.get("learning_objective", ""),
                        reason=c.get("reason", ""),
                        keywords=list(c.get("keywords", []) or []),
                        structure_tags=list(c.get("structure_tags", []) or []),
                        scores=scores,
                        low_educational_value=bool(c.get("low_educational_value", False)),
                    )
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("후보 파싱 실패, 건너뜀: %s (%s)", c, e)
                continue
    return candidates


def analyze_transcript(
    transcript: Transcript,
    cfg: dict[str, Any],
    max_length_seconds: int,
    progress: ProgressCallback = None,
) -> tuple[list[ShortCandidate], dict[str, str]]:
    """전체 파이프라인: 유형 판단 → 청크별 후보 추출."""
    model = cfg["claude_model"]

    content_type_info = detect_content_type(transcript, model, progress)
    subject = content_type_info.get("subject", "기타")
    guidance = cfg["type_guidance"].get(subject, cfg["type_guidance"].get("기타", ""))

    if progress:
        progress(f"콘텐츠 유형: {subject} / {content_type_info.get('content_type')}")

    chunks = list(iter_chunks(transcript, cfg["chunk_minutes"], cfg["chunk_overlap_seconds"]))
    all_candidates: list[ShortCandidate] = []
    for i, (s_idx, e_idx) in enumerate(chunks):
        if progress:
            progress(f"AI 분석 중... ({i + 1}/{len(chunks)} 구간)")
        try:
            cands = analyze_chunk(transcript, s_idx, e_idx, content_type_info, guidance, max_length_seconds, model)
            all_candidates.extend(cands)
        except AnthropicNotConfigured:
            raise
        except Exception as e:  # noqa: BLE001 - 한 청크 실패로 전체를 멈추지 않는다
            logger.exception("청크 분석 실패 (%s-%s): %s", s_idx, e_idx, e)
            if progress:
                progress(f"구간 {i + 1} 분석 중 오류 발생 — 건너뜀 ({e})")

    return all_candidates, content_type_info
