"""자기소개서 글을 점검한다.

새 문장을 지어내지 않는다. **학생이 쓴 글에서 고칠 만한 지점을 짚어줄 뿐이다.**
AI 가 그럴듯한 문장을 만들어주면 겪지 않은 일을 쓰게 되고, 면접에서 무너진다.
자기소개서는 본인 경험을 본인 말로 써야 하는 글이다.

무엇을 보는가
  1) 구조   — 언제·무엇을·어떻게·그래서 무엇을 배웠는지가 들어 있는가
  2) 문장   — 너무 길거나, 같은 말이 반복되거나, 추상적이지 않은가
  3) 분량   — 항목에 견주어 너무 짧거나 길지 않은가
"""

import re
from typing import Dict, List

# 구체적인 경험을 쓸 때 자연스럽게 나오는 표현들.
# 하나도 없으면 "무슨 일이 있었는지"가 빠진 글일 가능성이 높다.
SIGNALS = {
    "when": {
        "label": "언제 있었던 일인지",
        "hint": "1학년 때, 지난 5월, 실습 시간에 처럼 시점을 넣어보세요.",
        "words": ["학년", "학기", "월", "때", "당시", "무렵", "동안", "주에", "년"],
    },
    "what": {
        "label": "무엇을 했는지",
        "hint": "맡은 역할과 한 일을 구체적으로 적어보세요.",
        "words": ["맡", "했다", "만들", "참여", "준비", "진행", "제작", "발표",
                  "실습", "과제", "프로젝트", "대회", "활동"],
    },
    "how": {
        "label": "어떻게 했는지",
        "hint": "어떤 방법으로 해결했는지가 들어가면 설득력이 생깁니다.",
        "words": ["방법", "찾", "나눠", "정리", "연습", "확인", "분석", "고쳐",
                  "바꿔", "시도", "물어", "검색", "조사"],
    },
    "learn": {
        "label": "무엇을 배웠는지",
        "hint": "그 경험에서 얻은 것과 앞으로의 다짐으로 마무리해보세요.",
        "words": ["배웠", "깨달", "알게", "느꼈", "생각하게", "앞으로", "다짐",
                  "성장", "달라졌", "중요하다"],
    },
}

# 뜻이 흐릿해 아무 말도 하지 않는 표현들.
VAGUE = [
    ("열심히", "얼마나·어떻게 했는지로 바꿔보세요"),
    ("최선을 다", "구체적으로 무엇을 했는지 적어보세요"),
    ("많은 것을 배웠", "무엇을 배웠는지 하나만 콕 집어보세요"),
    ("좋은 경험이", "그 경험이 어떻게 좋았는지 적어보세요"),
    ("다양한 활동", "어떤 활동이었는지 이름을 적어보세요"),
    ("여러 가지", "무엇무엇인지 나열해보세요"),
    ("성실하게", "성실함이 드러난 장면을 적어보세요"),
    ("노력했", "어떤 노력이었는지 적어보세요"),
    ("도움이 되었", "무엇에 어떻게 도움이 됐는지 적어보세요"),
]

LONG_SENTENCE = 90        # 이보다 길면 읽기 어렵다
SHORT_TEXT = 150          # 자소서 한 항목으로는 너무 짧다
REPEAT_MIN_LEN = 2        # 반복을 셀 낱말의 최소 길이
REPEAT_LIMIT = 4          # 같은 낱말이 이보다 많이 나오면 지적


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


def check_structure(text: str) -> List[Dict]:
    """빠진 요소를 알려준다. 다 채우라는 뜻은 아니고, 점검용이다."""
    body = (text or "").replace(" ", "")
    missing = []
    for key, spec in SIGNALS.items():
        if not any(w.replace(" ", "") in body for w in spec["words"]):
            missing.append({"key": key, "label": spec["label"], "hint": spec["hint"]})
    return missing


def check_sentences(text: str) -> List[Dict]:
    """문장 단위로 고칠 만한 곳을 찾는다."""
    found = []

    for s in split_sentences(text):
        if len(s) > LONG_SENTENCE:
            found.append({
                "level": "maybe",
                "kind": "long",
                "target": s[:40] + "…",
                "reason": f"한 문장이 {len(s)}자로 깁니다. 두 문장으로 나눠보세요.",
            })

    body = text or ""
    for word, hint in VAGUE:
        idx = body.find(word)
        if idx >= 0:
            found.append({
                "level": "maybe",
                "kind": "vague",
                "target": word,
                "reason": hint,
            })

    # 같은 낱말이 지나치게 반복되는지. 조사를 떼지 않으므로 넉넉히 잡는다.
    words = re.findall(r"[가-힣]{2,}", body)
    counts: Dict[str, int] = {}
    for w in words:
        if len(w) >= REPEAT_MIN_LEN:
            counts[w] = counts.get(w, 0) + 1
    for w, n in sorted(counts.items(), key=lambda x: -x[1]):
        if n > REPEAT_LIMIT:
            found.append({
                "level": "maybe",
                "kind": "repeat",
                "target": w,
                "reason": f"'{w}' 가 {n}번 나옵니다. 다른 말로 바꿔보세요.",
            })
            break      # 가장 많은 것 하나만 알려준다

    return found


def review(text: str, limit: int = 1000) -> Dict:
    """한 항목을 점검한다."""
    body = (text or "").strip()
    length = len(body)

    notes = []
    if length == 0:
        return {"length": 0, "missing": [], "notes": [], "ok": False,
                "summary": "아직 내용이 없습니다."}
    if length < SHORT_TEXT:
        notes.append({
            "level": "maybe", "kind": "short", "target": "",
            "reason": f"{length}자로 짧습니다. 겪은 일을 더 구체적으로 적어보세요.",
        })
    if length > limit:
        notes.append({
            "level": "sure", "kind": "over", "target": "",
            "reason": f"{length}자로 제한({limit}자)을 넘었습니다. 줄여야 합니다.",
        })

    missing = check_structure(body)
    notes.extend(check_sentences(body))

    if not missing and not notes:
        summary = "구조와 문장 모두 무리가 없습니다."
    elif missing:
        summary = f"{', '.join(m['label'] for m in missing[:2])}가 잘 드러나지 않습니다."
    else:
        summary = "다듬으면 더 읽기 좋아질 곳이 있습니다."

    return {
        "length": length,
        "missing": missing,
        "notes": notes,
        "ok": not missing and not notes,
        "summary": summary,
    }


def review_many(fields: Dict[str, str], limit: int = 1000) -> Dict[str, Dict]:
    return {k: review(v, limit) for k, v in (fields or {}).items() if (v or "").strip()}
