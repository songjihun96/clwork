"""포트폴리오 도메인 상수와 1차(비-AI) 테마 추천 로직.

`ai.py`의 `RESUME_KEYWORDS`/`score_text`/`match_resume_topics`와 같은 방식을
그대로 따른다 — AI를 부르기 전에 서버가 키워드로 후보를 추리고, 점수와
관련 기록 수만 학생에게 보여준다("협업 능력 87점"이 아니라 "관련 기록
12개"). AI는 이 후보를 문구로 다듬는 역할만 한다.
"""

from typing import Dict, List

# ── 테마 ────────────────────────────────────────────────────
THEME_TYPES = [
    "growth", "problem_solving", "project", "major", "collaboration",
    "exploration", "school_life", "career", "custom",
]
THEME_LABEL = {
    "growth": "성장",
    "problem_solving": "문제 해결",
    "project": "프로젝트/작품",
    "major": "전공 역량",
    "collaboration": "협업",
    "exploration": "탐구/관심",
    "school_life": "학교생활",
    "career": "진로",
    "custom": "자유",
}

PURPOSE_TYPES = ["growth", "university", "employment", "interview", "school_life", "free"]
PURPOSE_LABEL = {
    "growth": "성장 기록", "university": "진학용", "employment": "취업용",
    "interview": "면접 대비", "school_life": "학교생활 정리", "free": "자유",
}

# 테마를 걸러낼 때 쓰는 단서 낱말. ai.RESUME_KEYWORDS와 같은 방식(부분일치,
# 형태소 분석기 없이 어간만 적어 어미 변화에 대응)이다. career/school_life는
# 일지에 재료가 적어 넓게 잡는다.
THEME_KEYWORDS: Dict[str, List[str]] = {
    "growth": [
        "성장", "달라졌", "나아지", "발전", "꾸준", "노력", "연습", "극복",
        "부족", "보완", "고치", "배웠", "깨달", "느꼈", "다짐",
    ],
    "problem_solving": [
        "문제", "오류", "에러", "고장", "안 되", "안되", "실패", "해결",
        "원인", "찾아", "고쳤", "수정", "다시 해", "방법", "시행착오",
    ],
    "project": [
        "프로젝트", "제작", "만들", "개발", "완성", "작품", "설계", "구현",
        "과제", "발표", "대회", "공모전", "출품",
    ],
    "major": [
        "실습", "전공", "이론", "기능", "자격증", "기술", "현장", "실무",
        "장비", "도구", "실험", "측정", "시공", "조리", "설계도", "도면",
    ],
    "collaboration": [
        "팀", "조원", "모둠", "같이", "함께", "협력", "협업", "분담", "역할",
        "맡", "회의", "소통", "갈등", "조율", "배려", "양보",
    ],
    "exploration": [
        "궁금", "찾아보", "조사", "탐구", "관심", "스스로", "혼자", "독학",
        "새로운", "시도", "도전", "실험", "알아보",
    ],
    "school_life": [
        "동아리", "봉사", "행사", "축제", "체육대회", "학급", "친구", "선생님",
        "상담", "활동",
    ],
    "career": [
        "진로", "직무", "취업", "꿈", "장래", "적성", "희망", "미래", "계획",
        "면접", "지원",
    ],
}

# 학과 계열별 기본 우선순위(높은 순). dept_fields.py의 계열 키와 짝을 맞춘다.
# "학생 능력 평가"가 아니라 "어떤 포트폴리오 형태가 학과와 잘 맞는지"를
# 판단하는 데만 쓴다 — 실제로 어떤 테마를 추천하는지는 결국 학생 기록의
# 실제 개수(THEME_KEYWORDS 매칭)가 정한다. 이 우선순위는 개수가 비슷할 때
# 순서를 정하는 타이브레이커일 뿐이다.
DEFAULT_THEME_PRIORITY: Dict[str, List[str]] = {
    "information_software": ["project", "problem_solving", "major", "growth", "collaboration"],
    "electrical_electronics": ["project", "growth", "problem_solving", "major", "collaboration"],
    "mechanical_automotive": ["project", "growth", "problem_solving", "major", "collaboration"],
    "culinary_food": ["project", "growth", "problem_solving", "collaboration", "major"],
    "accounting_office": ["major", "problem_solving", "collaboration", "growth", "exploration"],
    "tourism_hotel": ["collaboration", "problem_solving", "major", "growth", "exploration"],
    "architecture_design": ["project", "growth", "exploration", "problem_solving", "major"],
    "content_media": ["project", "growth", "exploration", "problem_solving", "collaboration"],
    "beauty": ["project", "growth", "major", "exploration", "collaboration"],
    "health_welfare": ["collaboration", "major", "growth", "problem_solving", "exploration"],
    "business_marketing": ["major", "problem_solving", "collaboration", "growth", "exploration"],
    "agriculture_bio": ["growth", "project", "problem_solving", "major", "collaboration"],
    "other": ["growth", "project", "problem_solving", "collaboration", "exploration"],
}

MIN_SCORE = 2   # ai.MATCH_MIN_SCORE와 같은 값. 우연히 한 단어만 걸린 건 버린다.


def score_text(text: str, keywords: List[str]) -> tuple:
    body = (text or "").replace(" ", "")
    hits = [w for w in keywords if w.replace(" ", "") in body]
    return len(hits), hits


def score_themes(entries: List[dict], dept_field: str = "other") -> List[dict]:
    """일지 모음을 테마별로 채점한다.

    entries: [{id, entry_date, kind, text}, ...] (journal_content를 이미
    합쳐 하나의 글로 만든 상태로 넘어와야 한다)

    반환은 관련 기록이 하나라도 있는 테마만, 우선순위(학과 계열 타이브레이커)
    와 관련 기록 수 순으로 정렬해서 준다.
    """
    priority = DEFAULT_THEME_PRIORITY.get(dept_field, DEFAULT_THEME_PRIORITY["other"])
    rank = {t: i for i, t in enumerate(priority)}

    out = []
    for theme, keywords in THEME_KEYWORDS.items():
        matched = []
        for e in entries:
            text = (e.get("text") or "").strip()
            if len(text) < 15:
                continue
            score, hits = score_text(text, keywords)
            if score < MIN_SCORE:
                continue
            matched.append({"journal_id": e["id"], "entry_date": e.get("entry_date", ""),
                            "score": score, "keywords": hits[:5]})
        if not matched:
            continue
        matched.sort(key=lambda m: -m["score"])
        out.append({
            "theme_type": theme,
            "title": THEME_LABEL.get(theme, theme),
            "source_count": len(matched),
            "matches": matched,
            "_rank": rank.get(theme, 99),
        })

    out.sort(key=lambda t: (t["_rank"], -t["source_count"]))
    for t in out:
        del t["_rank"]
    return out


# ── 블록 ────────────────────────────────────────────────────
ALLOWED_BLOCK_TYPES = {
    "heading", "text", "image", "image_gallery", "quote", "tag", "timeline",
    "project_info", "result", "experience", "file", "divider", "spacer",
}

# 컴퓨터 용어를 그대로 노출하지 않기 위한 배치 옵션. 프론트가 이 값만
# 고르게 하고, 실제 CSS는 프론트에서 이 값을 보고 정한다(서버는 값만 검증).
ALLOWED_LAYOUTS = {
    "stack", "side_by_side", "two_col", "three_col", "center", "large", "small",
}

# ── AI Action ───────────────────────────────────────────────
# 자연어 명령을 이 목록 밖의 행동으로 확장하지 않는다. 서버가 화이트리스트로
# 최종 검증한다 — AI가 뭐라고 답하든 여기 없는 action은 실행하지 않는다.
ALLOWED_AI_ACTIONS = {
    "TEXT_EDIT", "TEXT_SHORTEN", "TEXT_EXPAND", "TEXT_PROOFREAD", "TITLE_SUGGEST",
    "IMAGE_RESIZE", "IMAGE_ALIGN", "IMAGE_CAPTION",
    "BLOCK_MOVE", "BLOCK_DELETE", "BLOCK_DUPLICATE",
    "PAGE_MOVE", "PAGE_DUPLICATE", "PAGE_ADD",
    "LAYOUT_CHANGE",
}
