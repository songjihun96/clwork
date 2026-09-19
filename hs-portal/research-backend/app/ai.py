"""학교생활 일지/수업 일지 → 자소서·생기부 요약 변환 모듈.

동작 방식(2단계 폴백):
  1) AI_SUMMARIZER=kobart 이고 transformers/torch가 설치돼 있으면 KoBART 요약 모델 사용
  2) 그렇지 않으면 의존성 없는 '추출 요약'(문장 점수화)으로 동작

서버 메모리가 작을 수 있으므로 모델은 최초 요청 때 한 번만 지연 로딩(lazy load)한다.
gunicorn 워커가 여러 개면 워커마다 모델이 올라가므로, KoBART를 켤 때는
워커 수를 1로 줄이는 것을 권장한다(README 참고).
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------- 설정
MODEL_NAME = os.getenv("AI_MODEL_NAME", "gogamza/kobart-summarization")
USE_KOBART = os.getenv("AI_SUMMARIZER", "").strip().lower() == "kobart"

_pipe = None          # 로드된 요약 파이프라인
_load_failed = False  # 로드 실패 시 재시도하지 않는다


def _get_pipe():
    """KoBART 요약 파이프라인을 지연 로딩. 실패하면 None(추출 요약으로 폴백)."""
    global _pipe, _load_failed
    if _pipe is not None or _load_failed or not USE_KOBART:
        return _pipe
    try:
        from transformers import pipeline  # 무거우므로 함수 안에서 import

        _pipe = pipeline("summarization", model=MODEL_NAME)
    except Exception:
        _load_failed = True
        _pipe = None
    return _pipe


def backend_name() -> str:
    """현재 요약 엔진 이름(관리자 확인용)."""
    if USE_KOBART and _get_pipe() is not None:
        return f"kobart:{MODEL_NAME}"
    return "extractive"


# ---------------------------------------------------------------- 문장 처리
_SENT_END = re.compile(r"(?<=[.!?。])\s+|\n+")
_STOPWORDS = {
    "그리고", "그래서", "하지만", "그러나", "정말", "너무", "매우", "조금", "다시",
    "우리", "저는", "제가", "나는", "내가", "것을", "것이", "때문에", "통해", "대해",
    "있다", "했다", "한다", "된다", "이다", "이런", "저런", "그런", "많이", "같은",
}


def split_sentences(text: str) -> List[str]:
    """한국어 문장 분리(마침표가 없어도 줄바꿈 기준으로 나눈다)."""
    if not text:
        return []
    parts = [s.strip() for s in _SENT_END.split(text) if s and s.strip()]
    # 마침표 없이 길게 쓴 경우 대비: 너무 긴 문장은 쉼표 기준으로 한 번 더 분리
    out: List[str] = []
    for p in parts:
        if len(p) > 160 and "," in p:
            out.extend([q.strip() for q in p.split(",") if q.strip()])
        else:
            out.append(p)
    return [s for s in out if len(s) >= 5]


def _keywords(text: str) -> Dict[str, int]:
    words = re.findall(r"[가-힣A-Za-z]{2,}", text)
    freq: Dict[str, int] = {}
    for w in words:
        if w in _STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    return freq


def extractive_summary(text: str, max_sentences: int = 2) -> str:
    """의존성 없는 추출 요약: 단어 빈도로 문장을 점수화해 핵심 문장을 고른다."""
    sents = split_sentences(text)
    if not sents:
        return ""
    if len(sents) == 1:
        return sents[0]
    # 문장이 적어도 최소 한 문장은 덜어내어 '요약'이 되도록 한다
    max_sentences = max(1, min(max_sentences, len(sents) - 1))

    freq = _keywords(text)
    scored = []
    for i, s in enumerate(sents):
        words = re.findall(r"[가-힣A-Za-z]{2,}", s)
        if not words:
            continue
        score = sum(freq.get(w, 0) for w in words) / (len(words) ** 0.5)
        if i == 0:  # 첫 문장 가산점(주제 문장인 경우가 많음)
            score *= 1.15
        scored.append((score, i, s))

    scored.sort(key=lambda x: -x[0])
    picked = sorted(scored[:max_sentences], key=lambda x: x[1])
    return " ".join(s for _, _, s in picked)


def summarize(text: str, max_sentences: int = 2) -> str:
    """요약 진입점. KoBART가 있으면 생성 요약, 없으면 추출 요약."""
    text = (text or "").strip()
    if len(text) < 40:  # 너무 짧으면 원문 그대로
        return text

    pipe = _get_pipe()
    if pipe is not None:
        try:
            result = pipe(text[:1024], max_length=128, min_length=20, do_sample=False)
            summary = (result[0].get("summary_text") or "").strip()
            if summary:
                return summary
        except Exception:
            pass  # 실패 시 추출 요약으로 폴백
    return extractive_summary(text, max_sentences=max_sentences)


def pick_quotes(text: str, limit: int = 2) -> List[str]:
    """학생이 실제로 쓴 문장 중 인용하기 좋은 문장을 원문 그대로 고른다.
    (요약과 달리 문장을 변형하지 않으므로 '인용문'으로 쓸 수 있다)"""
    sents = split_sentences(text)
    if not sents:
        return []
    freq = _keywords(text)
    scored = []
    for s in sents:
        if len(s) < 12:  # 너무 짧은 문장은 인용 가치가 낮다
            continue
        words = re.findall(r"[가-힣A-Za-z]{2,}", s)
        if not words:
            continue
        score = sum(freq.get(w, 0) for w in words) / (len(words) ** 0.5)
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]


# ---------------------------------------------------------------- 양식 정의
# 일지 종류별 입력 항목. (키, 라벨, 자소서에서의 역할)
LESSON_FIELDS = [
    ("objective", "학습 목적"),
    ("goal", "학습 목표"),
    ("content", "수업 내용"),
    ("feeling", "수업을 통해 느낀 점"),
    ("problem", "해결하지 못하거나 이해하지 못해 어려웠던 부분"),
    ("solution", "해결하기 위한 방법"),
    ("result", "결과 및 느낀 점"),
]

DIARY_FIELDS = [
    ("memorable", "가장 기억에 남는 수업/활동/사건"),
    ("reason", "기억에 남는 이유"),
    ("lesson", "얻게 된 교훈 또는 깨달은 부분"),
    ("apply", "실천 및 적용할 수 있는 부분"),
]

FIELDS = {"lesson": LESSON_FIELDS, "diary": DIARY_FIELDS}

KIND_LABEL = {"lesson": "수업 일지", "diary": "학교생활 일지"}

# 자소서 항목. 화면·내려받기·AI 재료찾기가 모두 이 순서를 따른다.
RESUME_TEMPLATES = {
    "strength": "자신의 강점을 강화시키고 약점을 관리했던 경험",
    "problem_solving": "직무와 관련된 역량을 키우던 중 자신이 맡았던 역할과 "
                       "문제 발생 시 해결했던 경험",
    "teamwork": "팀 활동에서 본인의 역할을 책임감 있게 수행했던 경험",
    "conflict": "팀/개인적으로 사람과의 관계에서 힘들었던 갈등 상황과 극복 경험",
    "rule": "팀/조직의 중요한 규정이나 지침, 원칙을 지키기 위해 노력한 경험",
    "sacrifice": "팀/조직의 이익을 위해 자신이 희생했던 경험",
    "challenge": "팀/개인적으로 도전과 목표를 성취했던 경험",
    "failure": "계획대로 되지 않았거나 실패했던 경험과, 그 과정에서 배웠던 경험",
    "weakness": "자신의 부족한 점과 이를 보완하기 위해 현재 하고 있는 노력",
    "learning": "새로운 지식이나 기술을 배우기 위해 스스로 노력했던 경험",
    "job_motive": "해당 직무(분야)를 선택하게 된 계기와 그 직무를 위해 준비해 온 것",
    "apply_motive": "회사에 지원한 이유(지원동기)",
    "future_goal": "입사 후 이루고 싶은 목표 (단기 1~3년 / 장기 5년 이후)",
}

# 예전 양식에만 있던 항목. 이미 쓴 학생의 글을 잃지 않으려고 이름만 남겨 둔다.
# 새로 고를 수는 없고, 내용이 있는 학생에게만 화면과 내려받기에 나타난다.
LEGACY_TEMPLATES = {
    "growth": "성장과정",
    "personality": "성격의 장/단점",
    "school_life": "학교생활",
}

ALL_TEMPLATES = {**RESUME_TEMPLATES, **LEGACY_TEMPLATES}

# 첫 항목. 어디선가 항목을 안 정하고 부를 때 쓴다.
DEFAULT_TEMPLATE = next(iter(RESUME_TEMPLATES))

# 자소서 항목별로 일지를 골라내는 단서 낱말.
# 형태소 분석기 없이 부분 일치로 찾으므로, 어미가 붙어도 걸리도록 어간만 적는다.
# (예: "맡" 이면 맡았다/맡아서/맡은 이 모두 걸린다)
RESUME_KEYWORDS = {
    "strength": [
        "강점", "장점", "잘하는", "잘한", "자신있", "자신 있", "특기",
        "약점", "단점", "부족", "보완", "고치", "연습", "노력", "극복",
    ],
    "problem_solving": [
        "문제", "오류", "에러", "고장", "안 되", "안되", "실패",
        "해결", "원인", "찾아", "고쳤", "수정", "다시 해", "방법",
        "실습", "과제", "프로젝트", "작업",
    ],
    "teamwork": [
        "팀", "조원", "모둠", "같이", "함께", "협력", "협업", "분담",
        "역할", "맡", "책임", "회의", "발표",
    ],
    "conflict": [
        "갈등", "다툼", "싸", "오해", "서운", "속상", "마찰", "불편",
        "화해", "사과", "풀렸", "대화", "이해하", "맞춰",
    ],
    "rule": [
        "규칙", "규정", "약속", "원칙", "지침", "매뉴얼",
        "안전", "질서", "정리", "지키", "준수", "챙기",
    ],
    "sacrifice": [
        "양보", "희생", "대신", "도와", "도움", "봉사", "남아서",
        "먼저", "배려", "챙겨", "맡아서",
    ],
    "challenge": [
        "도전", "목표", "대회", "자격증", "시험", "공모전", "준비",
        "성취", "해냈", "달성", "합격", "이뤘", "끝까지", "완성",
    ],
    "failure": [
        # 잘 안 된 일과 거기서 배운 것. 일지에 가장 많이 남는 대목이다.
        "실패", "안 됐", "안됐", "못했", "못 했", "망쳤", "틀렸",
        "아쉬", "후회", "부족했", "생각대로", "계획대로", "뜻대로",
        "다시 해", "다시 했", "그래서 배", "배웠", "깨달", "교훈",
    ],
    "weakness": [
        # 지금 고쳐 나가는 중인 것. '했다'가 아니라 '하고 있다'가 신호다.
        "부족", "약점", "단점", "모자", "서툴", "어려웠",
        "보완", "채우", "고치려", "나아지", "연습 중", "공부 중",
        "노력하고 있", "하고 있습니다", "매일", "꾸준",
    ],
    "learning": [
        # 시켜서가 아니라 스스로 찾아 배운 것
        "배우", "배웠", "익히", "익혔", "독학", "스스로", "혼자",
        "찾아보", "검색", "유튜브", "인강", "책을", "자료를",
        "자격증", "공부", "연습했", "따라 해", "만들어 봤",
    ],
    "job_motive": [
        # 이 분야를 고르게 된 까닭과 그동안 준비한 것
        "진로", "직무", "분야", "전공", "학과", "계기", "관심",
        "되고 싶", "꿈", "장래", "적성", "현장", "실습", "견학",
        "자격증", "준비", "취업",
    ],
    # 아래 둘은 회사와 미래에 관한 글이라 일지에 재료가 거의 없다.
    # 그래도 진로를 말한 대목이 있으면 참고가 되므로 넓게 잡아 둔다.
    "apply_motive": [
        "회사", "기업", "취업", "지원", "면접", "산업체", "현장실습",
        "직무", "진로", "일하고 싶",
    ],
    "future_goal": [
        "목표", "앞으로", "계획", "되고 싶", "이루", "꿈",
        "장래", "성장", "다짐", "노력하겠",
    ],
}

# 일지에서 재료를 찾기 어려운 항목. 화면에서 그 사실을 미리 알려준다.
# 회사와 미래에 관한 글이라, 지난 일을 적은 일지에는 단서가 거의 없다.
LOOSE_TOPICS = {"apply_motive", "future_goal"}

# 이 점수 미만이면 억지로 끼워 맞춘 것으로 보고 버린다.
MATCH_MIN_SCORE = 2


def score_text(text: str, keywords) -> tuple:
    """본문이 항목에 얼마나 맞는지 점수와 근거 낱말을 돌려준다."""
    body = (text or "").replace(" ", "")
    hits = []
    for word in keywords:
        if word.replace(" ", "") in body:
            hits.append(word)
    return len(hits), hits


def match_resume_topics(entries, limit_per_topic: int = 3):
    """일지 모음을 자소서 항목별로 분류한다.

    entries: [{id, kind, entry_date, field_key, field_label, text}, ...]
    각 항목마다 점수가 높은 순으로 골라 요약과 원문을 함께 돌려준다.
    요약은 문장을 새로 지어내지 않고 학생이 쓴 문장에서 뽑아낸다.
    """
    result = []
    for key, keywords in RESUME_KEYWORDS.items():
        scored = []
        for e in entries:
            text = (e.get("text") or "").strip()
            if len(text) < 20:      # 한두 마디는 자소서 재료가 되지 않는다
                continue
            score, hits = score_text(text, keywords)
            # 단서가 하나뿐이면 우연히 걸린 것일 가능성이 크다.
            # 억지로 채우면 엉뚱한 대목이 재료로 올라와 오히려 방해가 된다.
            if score < MATCH_MIN_SCORE:
                continue
            scored.append((score, e, hits))

        scored.sort(key=lambda x: (-x[0], -len(x[1].get("text", ""))))
        picked = scored[:limit_per_topic]

        result.append({
            "key": key,
            "label": ALL_TEMPLATES.get(key, key),
            "loose": key in LOOSE_TOPICS,   # 참고용으로 넓게 고른 항목
            "count": len(scored),
            "matches": [
                {
                    "journal_id": e["id"],
                    "entry_date": e["entry_date"],
                    "kind_label": KIND_LABEL.get(e.get("kind"), e.get("kind", "")),
                    "field_label": e.get("field_label", ""),
                    "summary": summarize(e["text"], max_sentences=2),
                    "original": e["text"],
                    "keywords": hits[:5],
                }
                for score, e, hits in picked
            ],
        })
    return result



def field_labels(kind: str) -> List[tuple]:
    return FIELDS.get(kind, DIARY_FIELDS)


# ---------------------------------------------------------------- 변환기
def build_teacher_summary(kind: str, content: Dict[str, str]) -> List[dict]:
    """선생님용: 생기부에 넣을 수 있는 요약 목록.
    각 항목은 요약문과 함께 '원문'을 들고 있어, 클릭하면 원문을 펼쳐볼 수 있다."""
    items = []
    for key, label in field_labels(kind):
        original = (content.get(key) or "").strip()
        if not original:
            continue
        items.append(
            {
                "field": key,
                "label": label,
                "summary": summarize(original, max_sentences=2),
                "original": original,
            }
        )
    return items


def build_record_draft(kind: str, content: Dict[str, str], student_name: str = "") -> str:
    """선생님용: 생기부 문장체(음슴체) 초안. 요약을 이어 붙여 한 문단으로."""
    pieces = []
    for key, _label in field_labels(kind):
        original = (content.get(key) or "").strip()
        if not original:
            continue
        s = summarize(original, max_sentences=1)
        if s:
            pieces.append(_to_record_style(s))
    if not pieces:
        return ""
    body = " ".join(pieces)
    return body


_RECORD_ENDINGS = [
    # 특수형 먼저 (ㅂ니다 계열은 어간이 바뀌므로 개별 처리)
    (re.compile(r"합니다\.?$"), "함"),
    (re.compile(r"입니다\.?$"), "임"),
    (re.compile(r"됩니다\.?$"), "됨"),
    (re.compile(r"만듭니다\.?$"), "만듦"),
    (re.compile(r"옵니다\.?$"), "옴"),
    (re.compile(r"봅니다\.?$"), "봄"),
    (re.compile(r"씁니다\.?$"), "씀"),
    (re.compile(r"줍니다\.?$"), "줌"),
    # 일반형: '~습니다' → '~음'  (했습니다→했음, 이었습니다→이었음, 배웠습니다→배웠음)
    (re.compile(r"습니다\.?$"), "음"),
    # 평서체
    (re.compile(r"있다\.?$"), "있음"),
    (re.compile(r"없다\.?$"), "없음"),
    (re.compile(r"이다\.?$"), "임"),
    (re.compile(r"했다\.?$"), "했음"),
    (re.compile(r"[가-힣]다\.?$"), None),  # 그 외 '~다'는 그대로 둔다
]


def _to_record_style(sentence: str) -> str:
    """'~했습니다' 를 생기부에서 쓰는 '~함' 형태로 바꾼다."""
    s = sentence.strip()
    for pat, rep in _RECORD_ENDINGS:
        if pat.search(s):
            if rep is None:  # 변환 대상 아님(이미 평서체)
                break
            return pat.sub(rep + ".", s)
    if not s.endswith("."):
        s += "."
    return s


# ── 자소서 말투 다듬기 ─────────────────────────────────────
#
# 일지는 학생이 편하게 쓰는 글이라 줄임말과 구어체가 섞인다.
# 그 문장을 그대로 자소서에 옮기면 서류로 보이지 않는다.
# 여기서는 두 가지를 한다.
#   1) 서류에 넣으면 안 되는 말을 걸러낸다
#   2) 구어체를 '~습니다' 로 단정하게 바꾼다
#
# 뜻을 바꾸지는 않는다. 학생이 겪은 일은 학생의 것이고, 우리는 말투만
# 손본다. 걸러낸 자리는 지우지 않고 알려 주어 학생이 직접 고치게 한다.

# 서류에 그대로 두면 안 되는 말. 후기 검열보다 넓게 잡는다.
# 자소서는 남에게 보이는 서류라 '조금 거친 정도'도 걸러야 한다.
_RESUME_BLOCK = [
    # 욕설·비속어
    r"시[1i]?발", r"씨발", r"ㅅㅂ", r"ㅆㅂ", r"병신", r"ㅂㅅ", r"지랄", r"ㅈㄹ",
    r"개새", r"새끼", r"ㅈ같", r"좆", r"미친", r"꺼져", r"닥쳐", r"엿먹",
    r"찌질", r"멍청", r"등신", r"짜증", r"빡치", r"빡침", r"열받", r"개같",
    r"뒤지", r"디지", r"쳐먹", r"싸가지", r"재수없", r"밥맛",
    # 남을 깎아내리는 말
    r"무능", r"쓰레기", r"최악", r"한심", r"무시했", r"바보",
]
_RESUME_BLOCK_RE = re.compile("|".join(_RESUME_BLOCK))

# 구어체·줄임말을 서류 말투로 바꾼다. 앞이 긴 것부터 적어야
# '넘많이' 가 '넘' 으로 먼저 바뀌는 일이 없다.
_RESUME_REWRITE = [
    # 줄임말·인터넷말
    (r"어쩔\s*수\s*없이", "부득이하게"),
    (r"엄청\s*나게|엄청|되게|겁나|존나|넘\s*나|너무너무", "매우"),
    (r"짱\s*(?=[가-힣])", "매우 "),
    (r"쫌", "조금"),
    (r"좀\s*더", "조금 더"),
    (r"진짜로|진짜|리얼로|레알", "실제로"),
    (r"암튼|아무튼|여튼", "결과적으로"),
    (r"근데", "그러나"),
    (x_ := r"그래서\s*그런지", "그로 인해"),
    (r"막\s*(?=[가-힣])", ""),
    (r"뭔가\s*", ""),
    (r"좀\s*(?=[가-힣])", ""),
    (r"팀플", "팀 과제"),
    (r"쌤", "선생님"),
    (r"애들", "친구들"),
    (r"애가", "학생이"),
    (r"걔|쟤", "그 친구"),
    (r"핵\s*(?=[가-힣])", ""),
    (r"ㅋ+|ㅎ+|ㅠ+|ㅜ+|ㅡㅡ", ""),
    # 말끝
    (r"했음", "했습니다"),
    (r"됐음", "되었습니다"),
    (r"같음", "같습니다"),
    (r"인듯|인 듯", "인 것 같습니다"),
]
_RESUME_REWRITE_RE = [(re.compile(a), b) for a, b in _RESUME_REWRITE]

# 반말·구어체 종결을 '~습니다' 로 바꾼다. (문장 끝에서만)
# 위에서부터 차례로 보므로, 겹치는 것은 긴 쪽을 앞에 둔다.
_POLITE_TAIL_RAW = [
    ("되었어요", "되었습니다"), ("됐어요", "되었습니다"), ("됐다", "되었습니다"),
    ("했어요", "했습니다"), ("했었다", "했습니다"), ("했다", "했습니다"),
    ("봤어요", "보았습니다"), ("봤다", "보았습니다"),
    ("싶어요", "싶습니다"), ("싶다", "싶습니다"),
    ("같아요", "같습니다"), ("같다", "같습니다"),
    ("이에요", "입니다"), ("예요", "입니다"), ("이야", "입니다"),
    ("이다", "입니다"), ("였다", "였습니다"),
    ("났다", "났습니다"), ("왔다", "왔습니다"), ("갔다", "갔습니다"),
    ("었다", "었습니다"), ("았다", "았습니다"),
    ("한다", "합니다"), ("된다", "됩니다"),
    ("어요", "습니다"), ("아요", "습니다"),
]
_POLITE_TAIL = [(re.compile(re.escape(a) + r"([.]?)$"), b)
                for a, b in _POLITE_TAIL_RAW]


def polish_sentence(sentence: str) -> str:
    """문장 하나를 자소서 말투로 다듬는다. 뜻은 건드리지 않는다."""
    s = (sentence or "").strip()
    if not s:
        return ""

    for pat, rep in _RESUME_REWRITE_RE:
        s = pat.sub(rep, s)

    # 반말·구어체 종결을 '~습니다' 로 바꾼다.
    # 앞이 긴 것부터 손봐야 '됐어요' 가 '어요' 에 먼저 걸리지 않는다.
    for pat, rep in _POLITE_TAIL:
        m = pat.search(s)
        if m:
            s = s[:m.start()] + rep + (m.group(1) or "")
            break

    # 느낌표·물음표는 서류에 어울리지 않는다.
    s = re.sub(r"[!?]+", ".", s)
    # 다듬는 과정에서 생긴 겹공백 정리
    s = re.sub(r"\s{2,}", " ", s).strip()

    if s and not s.endswith((".", "다", "요")):
        s += "."
    return s


def polish_resume_text(text: str) -> dict:
    """자소서 본문을 다듬는다.

    반환: {"text": 다듬은 글, "changed": 바뀌었는지, "blocked": [걸린 말],
           "notes": [학생에게 알릴 말]}

    걸린 말을 몰래 지우지 않는다. 무엇이 왜 걸렸는지 알려 주고
    고치는 것은 학생이 하게 한다. 자기 글이기 때문이다.
    """
    original = (text or "").strip()
    if not original:
        return {"text": "", "changed": False, "blocked": [], "notes": []}

    blocked = sorted(set(_RESUME_BLOCK_RE.findall(original)))
    # findall 은 묶음이 있으면 묶음만 준다. 실제로 걸린 대목을 다시 찾는다.
    blocked = sorted({m.group(0) for m in _RESUME_BLOCK_RE.finditer(original)})

    lines = []
    for para in original.replace("\r\n", "\n").split("\n"):
        if not para.strip():
            lines.append("")
            continue
        sents = [polish_sentence(x) for x in split_sentences(para)]
        lines.append(" ".join(x for x in sents if x))
    polished = "\n".join(lines).strip()

    notes = []
    if blocked:
        notes.append(
            "서류에 어울리지 않는 표현이 있습니다: "
            + ", ".join(blocked[:5])
            + ". 다른 말로 바꿔 주세요."
        )
    if polished != original and not blocked:
        notes.append("구어체를 서류 말투로 다듬었습니다. 뜻이 맞는지 확인해 주세요.")

    return {
        "text": polished,
        "changed": polished != original,
        "blocked": blocked,
        "notes": notes,
    }


def build_resume(kind: str, content: Dict[str, str], template: str = "school_life") -> dict:
    """학생용: 선택한 자소서 항목 양식에 맞춰 초안을 만들고, 인용 가능한 문장을 뽑는다.

    반환: {"template", "template_label", "text", "quotes":[{text, field, label}]}
    """
    title = ALL_TEMPLATES.get(template, RESUME_TEMPLATES[DEFAULT_TEMPLATE])
    labels = dict(field_labels(kind))

    # 인용문: 학생이 쓴 문장 원문 그대로 (변형하지 않음)
    quotes: List[dict] = []
    for key, label in field_labels(kind):
        original = (content.get(key) or "").strip()
        if not original:
            continue
        for q in pick_quotes(original, limit=1):
            quotes.append({"text": q, "field": key, "label": label})

    # 본문 구성: 항목 성격에 맞게 [상황 → 행동 → 결과/배움] 흐름으로 배치
    if kind == "lesson":
        order = ["content", "problem", "solution", "result", "feeling"]
    else:
        order = ["memorable", "reason", "lesson", "apply"]

    paras: List[str] = []
    for key in order:
        original = (content.get(key) or "").strip()
        if not original:
            continue
        summary = summarize(original, max_sentences=2)
        if not summary:
            continue
        label = labels.get(key, "")
        paras.append(f"[{label}] {summary}")

    intro = f"■ 자기소개서 항목: {title}\n\n"
    body = "\n\n".join(paras) if paras else "작성된 내용이 없습니다."

    if quotes:
        cite = "\n\n■ 인용 가능한 내 문장\n" + "\n".join(
            f'· "{q["text"]}" ({q["label"]})' for q in quotes
        )
    else:
        cite = ""

    return {
        "template": template,
        "template_label": title,
        "text": intro + body + cite,
        "quotes": quotes,
    }


# ---------------------------------------------------------------- 리뷰 자동 검열
# 욕설·비방 표현. 자모 분리형(ㅅㅂ 등)과 우회 표기도 함께 잡는다.
_ABUSE_PATTERNS = [
    r"시[1i]?발", r"씨발", r"ㅅㅂ", r"ㅆㅂ", r"병신", r"ㅂㅅ", r"지랄", r"ㅈㄹ",
    r"개새", r"새끼", r"ㅈ같", r"좆", r"미친놈", r"미친년", r"꺼져", r"닥쳐",
    r"죽어라", r"죽어버", r"디져", r"뒤져", r"엿먹", r"찌질", r"멍청이", r"등신",
    r"쓰레기\s*학교", r"망해라", r"불태", r"패\s*버리",
]
_ABUSE_RE = re.compile("|".join(_ABUSE_PATTERNS))

# 개인 지목 저격 의심: 교사 호칭 '과 함께' 부정적 표현이 가까이 있을 때만 잡는다.
# (칭찬 리뷰의 "선생님들이 친절해서"까지 걸리면 안 되므로 부정어를 필수 조건으로 둔다)
_TITLE = r"(선생님?|쌤|교사|담임|교장|교감)"
_NEGATIVE = r"(최악|싫|짜증|무시|차별|편애|폭언|막말|욕|때리|괴롭|이상해|별로|끔찍|혐오)"
_TARGET_RE = re.compile(_TITLE + r"[^.!?\n]{0,20}" + _NEGATIVE)


def moderate_review(content: str, rating: int = 3) -> tuple:
    """리뷰 자동 검열. (보류할지, 사유) 를 돌려준다.

    악성으로 판단되면 자동 '보류(held)' 처리되어 공개되지 않고,
    선생님이 확인 후 보류 해제하거나 삭제한다.
    """
    text = (content or "").strip()
    if not text:
        return False, ""

    # 1) 욕설·비방 표현
    if _ABUSE_RE.search(text):
        return True, "욕설 또는 비방으로 의심되는 표현이 포함되어 있습니다."

    # 2) 같은 글자·문장부호 반복 (ㅋㅋㅋㅋㅋㅋ, !!!!!! 등 도배성)
    if re.search(r"(.)\1{7,}", text):
        return True, "같은 문자가 반복되는 도배성 내용으로 의심됩니다."

    # 3) 매우 낮은 평점 + 근거 없이 짧은 비난
    if rating <= 2 and len(text) < 15:
        return True, "낮은 평점에 비해 내용이 짧아 확인이 필요합니다."

    # 4) 특정 교사 지목 + 부정적 표현
    if _TARGET_RE.search(text):
        return True, "특정 인물에 대한 부정적 내용으로 보여 확인이 필요합니다."

    # 5) 연락처·링크 등 부적절한 정보
    if re.search(r"01[016-9][-\s]?\d{3,4}[-\s]?\d{4}|https?://", text):
        return True, "연락처 또는 외부 링크가 포함되어 있습니다."

    return False, ""


# ---------------------------------------------------------------- 키워드·주제 추출
# 조사/어미 제거용 (한국어 형태소 분석기 없이 명사 어근을 최대한 뽑는다)
_PARTICLES = (
    "으로써", "으로서", "에서는", "에게서", "이라고", "라고는", "부터는", "까지는",
    "으로", "에서", "에게", "한테", "보다", "처럼", "만큼", "라고", "이라", "든지",
    "이나", "거나", "면서", "지만", "는데", "는것", "하는", "했던", "하고", "이고",
    "과의", "와의", "의", "을", "를", "이", "가", "은", "는", "에", "도", "만",
    "과", "와", "로", "께", "야", "랑", "듯", "들", "씩", "쯤", "께서",
)

_KW_STOP = {
    "오늘", "내일", "어제", "이번", "다음", "정말", "진짜", "너무", "매우", "조금",
    "그리고", "하지만", "그래서", "그러나", "때문", "통해", "대해", "위해", "가장",
    "생각", "부분", "경우", "정도", "시간", "사람", "우리", "자신", "본인", "여러",
    "많이", "다시", "계속", "먼저", "함께", "모두", "다른", "같은", "이런", "그런",
    "끝까지", "중요성", "덕분", "이유", "이번주", "동안", "이후", "이전",
    # 의존명사·기능어
    "것을", "것이", "것은", "것도", "것과", "이를", "그를", "저를", "무엇", "어떤",
    "이것", "그것", "저것", "여기", "거기", "저기", "누구", "언제", "어디", "얼마",
    "하나", "여러", "각각", "모든", "다양", "일부", "대부분", "특히", "또한", "그런데",
    "관련", "대한", "위한", "따라", "통한", "의해", "인해", "그때", "당시", "이제",
    # 수업 일지 상투어 (변별력 없음)
    "개념", "원리", "실제", "적용", "이해", "목적", "목표", "과정", "방법", "결과",
    "능력", "기르", "향상", "배운", "학습", "내용을", "이번",
    "수업", "학교", "일지", "내용", "활동",  # 너무 흔해 변별력이 없는 말
}


# 동사·형용사 어미. 명사 어근만 남기기 위해 잘라낸다.
_VERB_TAILS = (
    "하였습니다", "했습니다", "되었습니다", "됐습니다", "이었습니다", "였습니다",
    "있었습니다", "없었습니다", "겠습니다", "았습니다", "었습니다", "습니다",
    "합니다", "됩니다", "입니다", "했다", "한다", "된다", "이다",
    "하는", "하고", "하지", "해서", "했던", "하며", "하면", "하기", "되는", "되어",
    "시키는", "시키기", "시켰", "시키", "시켜", "시킨",
    "하였", "하게", "되게", "되기", "받는", "받기", "당하",
    "이라는", "라는", "이라", "다는", "으며", "면서",
    "고자", "려고", "으려", "도록", "면서도", "지만",
)
def _has_ss_final(word: str) -> bool:
    """받침이 'ㅆ'인 글자가 있으면 동사 활용형(했/됐/느꼈/왔...)으로 본다.
    한글 음절을 분해해 종성 인덱스 20(ㅆ)인지 확인한다."""
    for ch in word:
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171 and code % 28 == 20:
            return True
    return False


def _root(word: str) -> str:
    """조사·어미를 떼어 명사 어근에 가깝게 만든다.
    '향상시키고자' 처럼 어미가 겹친 경우를 위해 변화가 없을 때까지 반복한다."""
    w = word
    for _ in range(4):
        prev = w
        w = _strip_once(w)
        if w == prev:
            break
    return w


def _strip_once(w: str) -> str:
    for t in _VERB_TAILS:
        if len(w) > len(t) + 1 and w.endswith(t):
            w = w[: -len(t)]
            break
    for p in sorted(_PARTICLES, key=len, reverse=True):
        if len(w) > len(p) + 1 and w.endswith(p):
            w = w[: -len(p)]
            break
    # 연결어미 한 글자 (발견해→발견, 노력하며→노력하)
    if len(w) > 2 and w[-1] in "해고며서":
        w = w[:-1]
    # 접미사 '적' (논리적→논리, 적극적→적극)
    if len(w) > 2 and w.endswith("적"):
        w = w[:-1]
    # 어간에 남은 '하'/'되' (노력하→노력, 발전되→발전)
    if len(w) > 2 and w[-1] in "하되":
        w = w[:-1]
    return w


def extract_keywords(text: str, limit: int = 6) -> List[str]:
    """글에서 핵심 키워드(명사 위주)를 빈도순으로 뽑는다."""
    words = re.findall(r"[가-힣]{2,}", text or "")
    freq: Dict[str, int] = {}
    for w in words:
        root = _root(w)
        if len(root) < 2 or root in _KW_STOP:
            continue
        # 활용형 잔여물 제외 (받침 ㅆ = 과거·축약형)
        if _has_ss_final(root):
            continue
        # 3글자 이상이면서 '다'로 끝나면 동사·형용사 종결형 (만든다, 중요하다)
        if len(root) >= 3 and root.endswith("다"):
            continue
        freq[root] = freq.get(root, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [w for w, _ in ranked[:limit]]


# 생활기록부·자소서에서 자주 쓰이는 역량 주제. (주제키, 라벨, 신호어)
TOPICS = [
    ("problem", "문제 해결", ["문제", "오류", "고장", "원인", "해결", "수정", "점검", "개선", "트러블", "디버깅", "실패", "보완"]),
    ("teamwork", "협업·팀워크", ["조원", "팀원", "협력", "협동", "함께", "역할분담", "분담", "모둠", "조별", "팀장", "소통", "의견"]),
    ("leadership", "리더십", ["리더", "팀장", "반장", "이끌", "주도", "설득", "제안", "책임감", "대표"]),
    ("challenge", "도전·목표", ["도전", "목표", "대회", "준비", "연습", "노력", "끝까지", "포기", "성취", "달성", "자격증", "시험"]),
    ("skill", "실습·기술 역량", ["실습", "장비", "기계", "프로그램", "코드", "회로", "설계", "제작", "측정", "용접", "조리", "디자인", "실기"]),
    ("career", "진로·취업", ["진로", "취업", "직무", "현장", "면접", "인턴", "기업", "산업체", "직업", "포트폴리오"]),
    ("attitude", "성실·태도", ["성실", "꾸준", "습관", "지각", "출석", "규칙", "약속", "정리", "준비물", "마무리"]),
    ("care", "배려·봉사", ["배려", "봉사", "도움", "도와", "나눔", "친구", "후배", "선배", "존중", "양보"]),
    ("growth", "성찰·성장", ["깨달", "배웠", "느꼈", "반성", "성장", "달라", "변화", "다짐", "앞으로"]),
]

TOPIC_LABEL = {k: label for k, label, _ in TOPICS}


def match_topics(text: str) -> List[str]:
    """글에 어떤 역량 주제가 담겨 있는지 판별한다(복수 가능)."""
    t = text or ""
    hits = []
    for key, _label, signals in TOPICS:
        if any(sig in t for sig in signals):
            hits.append(key)
    return hits


def topic_excerpt(text: str, topic_key: str, limit: int = 2) -> List[str]:
    """해당 주제의 신호어가 들어 있는 문장만 원문 그대로 뽑는다."""
    signals = next((s for k, _l, s in TOPICS if k == topic_key), [])
    out = []
    for sent in split_sentences(text):
        if any(sig in sent for sig in signals):
            out.append(sent)
            if len(out) >= limit:
                break
    return out
