"""숏츠가 롱폼의 어느 구간에서 잘려 나왔는지 찾는다(대본 기반).

**지금 앱이 쓰는 것은 이 파일의 일부뿐이다.** 구간 찾기는 소리 지문
(fingerprint.py)으로 옮겼고, 여기서는 clamp/decide_status/is_auto_confirmable
/DEFAULT_THRESHOLDS 만 쓴다. 아래 대본 정렬 코드는 지금 호출되지 않는다 —
바깥과 얽히지 않는 순수 함수들이고 검사도 그대로 통과하므로, 대본을 다시
쓰게 될 때를 위해 지우지 않고 남겨 둔다.


**왜 AI 에게 통째로 묻지 않나**

"이 숏츠가 롱폼 어디냐"고 LLM 에게 물으면 그럴듯한 시각을 지어낸다. 1시간
영상의 대본은 토큰 수만으로도 한 번에 넣기 어렵고, 넣더라도 03:24.12 같은
소수점 시각을 정확히 되돌려 줄 근거가 모델에게 없다. 우리가 필요한 건
'그럴듯한 위치'가 아니라 '실제로 잘린 자리'다.

그래서 검색 문제로 바꾼다. 롱폼 대본을 낱말 배열로 펴 두고, 숏츠 대본이
그 배열의 어디에 놓이는지를 **부분 문자열 정렬**로 찾는다. 낱말마다 시각이
붙어 있으므로, 맞은 첫 낱말과 마지막 낱말의 시각이 곧 구간이 된다.

**왜 완전 일치로 찾지 않나**

STT 는 같은 소리도 조금씩 다르게 받아 적는다("자신감입니다" / "자신감 입니다").
숏츠에는 인트로·아웃트로가 붙고 중간 문장이 잘려 나가기도 한다. 그래서
완전 일치 대신 (1) n-gram 으로 후보 자리를 좁히고 (2) 그 자리에서만 순서를
따지는 정렬을 돌린다. 롱폼 전체를 매번 정렬하면 느리고, 후보 없이 정렬만
하면 엉뚱한 자리에서도 그럴듯한 점수가 나온다.

이 파일은 DB 도 외부 API 도 건드리지 않는다. 순수 함수만 두어 실제 영상
없이도 검사할 수 있게 했다 — 실제로 영상 파일 없이 이 모듈만 따로 검사한다.
"""

from __future__ import annotations

import difflib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# 후보를 몇 개까지 돌려줄지. 관리자 화면에서 대안을 보여줄 때 쓴다.
MAX_CANDIDATES = 8

# 일치로 쳐 줄 최소 길이(글자).
#
# 한국어는 "니다" "에서" 같은 조각이, 심하게는 글자 하나가 영상 곳곳에서
# 걸린다. 그걸 그대로 두면 흩어진 한 글자들이 다리를 놓아 영상 전체가 한
# 구간으로 뭉쳐 버린다(실제로 "0.8초 ~ 1623초"가 나왔다). 3글자 이상만 본다.
MIN_MATCH_BLOCK = 3

# 구간 하나로 인정할 최소 누적 일치 길이.
MIN_BOUNDARY_BLOCK = 4

# 최종 confidence 를 만드는 가중치. 오디오 점수가 없으면(파일이 없거나
# 검증을 못 돌린 경우) 텍스트 쪽 가중치를 그만큼 키워서 다시 나눈다.
WEIGHTS = {"coverage": 0.45, "sequence": 0.35, "continuity": 0.05, "audio": 0.15}

# 오디오 점수를 '근거'로 인정하는 최저선.
#
# 숏츠에는 배경음악·자막 효과음이 깔리고 음량도 다시 잡는다. 그러면 원본에서
# 그대로 잘라낸 숏츠인데도 소리 무늬가 달라져 상관도가 0 에 가깝게 나온다.
# 그걸 감점으로 쓰면 텍스트가 88%·89% 로 잘 맞은 매칭까지 '확인 필요'로
# 떨어지고, 결국 관리자가 전부 손으로 확인해야 해서 기능이 무의미해진다.
#
# 그래서 오디오는 **올려 주기만 하고 깎지는 않는다**. 이 선을 넘으면 "같은
# 소리가 맞다"는 근거로 보고 신뢰도를 올리고, 못 넘으면 '판단 불가'로 보아
# 텍스트 점수만 쓴다. 낮은 점수도 화면에는 그대로 보여 준다 — 판단 근거를
# 숨기지는 않는다.
AUDIO_CONFIRM_MIN = 0.45

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """비교용으로 글자를 고른다.

    한글은 자모가 분리된 형태(NFD)로도 들어올 수 있어 NFC 로 모은다. 그러지
    않으면 눈에 같아 보이는 글자가 다른 문자열로 취급돼 매칭이 통째로 어긋난다.
    """
    t = unicodedata.normalize("NFC", text or "")
    t = _PUNCT.sub(" ", t)
    return _SPACE.sub(" ", t).strip().lower()


def tokenize(text: str) -> List[str]:
    n = normalize(text)
    return n.split(" ") if n else []


def char_view(tokens: Sequence[str]) -> Tuple[str, List[int]]:
    """낱말 배열을 (붙여 쓴 글자열, 글자→낱말 자리) 로 바꾼다.

    띄어쓰기를 없앤 글자열로 견주면 STT 사이의 띄어쓰기 차이가 통째로
    사라진다. 그래도 시각은 낱말에 붙어 있으므로, 글자마다 어느 낱말에서
    왔는지를 함께 들고 다녀야 구간을 되짚을 수 있다.
    """
    chars: List[str] = []
    owner: List[int] = []
    for i, tok in enumerate(tokens):
        for ch in tok:
            chars.append(ch)
            owner.append(i)
    return "".join(chars), owner


@dataclass
class Word:
    """낱말 하나와 그 낱말이 나온 시각(초)."""
    text: str
    start: float
    end: float


@dataclass
class Segment:
    """STT 가 돌려주는 한 덩어리(대개 문장 하나)."""
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)


@dataclass
class Candidate:
    start: float
    end: float
    coverage: float      # 숏츠 낱말 중 몇 %가 이 구간에서 발견됐나
    sequence: float      # 순서까지 맞는 정도
    continuity: float    # 맞은 낱말들이 끊기지 않고 이어지는 정도
    matched_words: int
    token_start: int     # 롱폼 낱말 배열에서의 자리(디버깅·재현용)
    token_end: int

    @property
    def text_score(self) -> float:
        """오디오를 빼고 텍스트만으로 본 점수."""
        w = WEIGHTS["coverage"] + WEIGHTS["sequence"] + WEIGHTS["continuity"]
        return (
            WEIGHTS["coverage"] * self.coverage
            + WEIGHTS["sequence"] * self.sequence
            + WEIGHTS["continuity"] * self.continuity
        ) / w


@dataclass
class MatchResult:
    start: Optional[float]
    end: Optional[float]
    confidence: float
    text_score: float
    sequence_score: float
    audio_score: Optional[float]
    method: str
    candidates: List[Candidate]
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.start is not None and self.end is not None


def flatten(segments: Sequence[Segment]) -> Tuple[List[str], List[Tuple[float, float]]]:
    """대본을 (낱말 배열, 시각 배열) 둘로 편다.

    낱말 단위 시각이 없는 STT 도 있다. 그럴 때는 문장의 시작·끝 사이를 낱말
    수로 고르게 나눠 쓴다. 정확도는 떨어지지만 구간을 못 찾는 것보다는 낫고,
    이후 보정 단계에서 문장 경계로는 맞출 수 있다.
    """
    tokens: List[str] = []
    times: List[Tuple[float, float]] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                for t in tokenize(w.text):
                    tokens.append(t)
                    times.append((float(w.start), float(w.end)))
            continue
        parts = tokenize(seg.text)
        if not parts:
            continue
        span = max(float(seg.end) - float(seg.start), 0.0)
        step = span / len(parts) if parts else 0.0
        for i, t in enumerate(parts):
            s = float(seg.start) + step * i
            tokens.append(t)
            times.append((s, s + step))
    return tokens, times


def _continuity(matched_positions: Sequence[int]) -> float:
    """맞은 낱말들이 끊기지 않고 이어지는 정도(0~1).

    같은 낱말이 영상 곳곳에 흩어져 우연히 맞은 경우와, 실제로 한 구간이
    통째로 맞은 경우를 가른다. 흩어진 쪽은 자리 간격이 들쭉날쭉하다.
    """
    if len(matched_positions) < 2:
        return 0.0 if not matched_positions else 1.0
    gaps = [b - a for a, b in zip(matched_positions, matched_positions[1:])]
    ideal = sum(1 for g in gaps if g == 1)
    return ideal / len(gaps)


def _cluster_blocks(blocks, gap_limit: int):
    """붙어 있는 일치 덩어리끼리 묶는다.

    롱폼 전체를 한 번에 맞추면 "니다" 같은 조각이 영상 곳곳에서 함께 걸린다.
    그대로 첫 덩어리와 끝 덩어리를 쓰면 구간이 영상 전체로 벌어진다.
    가까이 모여 있는 것끼리 묶어, 가장 촘촘한 묶음을 그 숏츠의 자리로 본다.
    """
    clusters: List[list] = []
    cur: list = []
    for b in blocks:
        if cur:
            prev = cur[-1]
            if b.a - (prev.a + prev.size) > gap_limit:
                clusters.append(cur)
                cur = []
        cur.append(b)
    if cur:
        clusters.append(cur)
    return clusters


def find_candidates(long_segments: Sequence[Segment],
                    short_segments: Sequence[Segment]) -> List[Candidate]:
    """숏츠가 나왔을 법한 롱폼 구간들을 점수 순으로 돌려준다.

    **롱폼 전체를 한 번에 맞춘다.** 예전에는 n-gram 으로 후보 자리를 찍고 그
    둘레만 창으로 떠서 견줬는데, 그 창이 어긋나면 숏츠 앞부분이 창 밖으로
    잘려 나갔다. 그러면 구간 시작이 뒤로 밀려서, 학생이 "전체 영상 보기"를
    눌렀을 때 숏츠 내용의 절반쯤이 이미 지나간 자리에서 재생됐다.

    전체를 맞추면 그 문제가 사라진다. 글자 단위 정렬은 앞뒤 순서를 지키므로
    (한 번 지나간 자리로 되돌아가지 않는다) 1시간짜리에도 한 번이면 된다.
    """
    long_tokens, long_times = flatten(long_segments)
    short_tokens, _ = flatten(short_segments)
    if not long_tokens or not short_tokens:
        return []

    long_chars, long_owner = char_view(long_tokens)
    short_chars, _ = char_view(short_tokens)
    if not long_chars or not short_chars:
        return []

    sm = difflib.SequenceMatcher(a=long_chars, b=short_chars, autojunk=False)
    # 짧은 우연 일치는 여기서 버린다. 남겨 두면 묶는 단계에서 다리 노릇을 해
    # 서로 먼 자리를 한 구간으로 이어 버린다.
    blocks = [b for b in sm.get_matching_blocks() if b.size >= MIN_MATCH_BLOCK]
    if not blocks:
        return []

    # 묶는 간격은 숏츠 길이의 1/3 쯤으로 좁게 잡는다.
    #
    # 넉넉히 잡았더니(숏츠 길이 전체) 영상 곳곳의 우연 일치가 하나로 뭉쳐
    # "0.8초 ~ 1623초"라는 구간이 나왔다. 진짜 구간이 그 안에 파묻혀 후보로
    # 올라오지도 못한다. 좁게 끊어 여러 후보로 만든 뒤 점수로 고르는 편이 낫다.
    gap_limit = max(len(short_chars) // 3, 12)
    out: List[Candidate] = []
    for group in _cluster_blocks(blocks, gap_limit):
        matched_chars = sum(b.size for b in group)
        if matched_chars < MIN_BOUNDARY_BLOCK:
            continue
        span_chars = (group[-1].a + group[-1].size) - group[0].a
        # 숏츠보다 훨씬 긴 자리에 띄엄띄엄 걸린 묶음은 그 숏츠의 출처가
        # 아니다. 그런 걸 후보로 두면 진짜 구간을 밀어낸다.
        if span_chars > len(short_chars) * 2.5 + 40:
            continue
        coverage = matched_chars / len(short_chars)

        # 이 묶음 안에서는 자잘한 일치도 경계로 인정한다. 어느 자리인지는
        # 이미 묶음으로 정해졌으므로, 여기서는 오히려 앞뒤를 넉넉히 잡아야
        # 숏츠 앞부분이 잘리지 않는다.
        first_char = group[0].a
        last_char = group[-1].a + group[-1].size - 1
        first = long_owner[first_char]
        last = long_owner[last_char]

        token_positions: List[int] = []
        for b in group:
            for k in range(b.a, b.a + b.size):
                t = long_owner[k]
                if not token_positions or token_positions[-1] != t:
                    token_positions.append(t)
        continuity = _continuity(token_positions)

        aligned = long_chars[first_char:last_char + 1]
        sequence = difflib.SequenceMatcher(
            a=aligned, b=short_chars, autojunk=False).ratio()

        out.append(Candidate(
            start=long_times[first][0],
            end=long_times[last][1],
            coverage=coverage, sequence=sequence, continuity=continuity,
            matched_words=matched_chars, token_start=first, token_end=last,
        ))
    out.sort(key=lambda c: -c.text_score)
    return out[:MAX_CANDIDATES]


def clamp(value: float, duration: Optional[float]) -> float:
    """실제 영상 길이를 벗어난 시각을 만들지 않는다."""
    v = max(float(value), 0.0)
    if duration and duration > 0:
        v = min(v, float(duration))
    return round(v, 2)


def combine_confidence(text_score: float, audio_score: Optional[float]) -> float:
    """텍스트 점수와 오디오 점수를 합쳐 최종 신뢰도를 만든다.

    오디오 검증을 못 돌린 경우(파일 없음·ffmpeg 없음)에는 그 몫을 빼고 남은
    가중치로 다시 나눈다. 오디오가 없다고 0점을 주면 멀쩡한 매칭이 전부
    needs_review 로 떨어진다.

    오디오 점수가 낮을 때도 마찬가지로 텍스트 점수만 쓴다. 이유는
    AUDIO_CONFIRM_MIN 주석 참고 — 낮은 오디오 점수는 '틀렸다'는 근거가
    아니라 '알 수 없다'에 가깝다.
    """
    if audio_score is None or float(audio_score) < AUDIO_CONFIRM_MIN:
        return round(min(max(text_score, 0.0), 1.0), 4)
    w_text = WEIGHTS["coverage"] + WEIGHTS["sequence"] + WEIGHTS["continuity"]
    total = w_text + WEIGHTS["audio"]
    mixed = (text_score * w_text + float(audio_score) * WEIGHTS["audio"]) / total
    # 섞은 값이 텍스트 점수보다 낮으면 텍스트 점수를 쓴다. 오디오는 '거들 뿐'
    # 이라, 텍스트가 만점인데 오디오가 0.99 라는 이유로 깎이면 안 된다.
    return round(min(max(mixed, text_score, 0.0), 1.0), 4)


def match(long_segments: Sequence[Segment], short_segments: Sequence[Segment],
          longform_duration: Optional[float] = None,
          audio_verify=None) -> MatchResult:
    """숏츠의 원본 구간을 찾는다.

    audio_verify: (start, end) -> 0~1 점수를 돌려주는 함수(선택). 후보를
        텍스트로 좁힌 뒤 **1등 후보에만** 부른다. 롱폼 전체를 오디오로 훑으면
        느리고, 텍스트가 이미 걸러 준 자리만 확인하면 충분하기 때문이다.
    """
    candidates = find_candidates(long_segments, short_segments)
    if not candidates:
        return MatchResult(None, None, 0.0, 0.0, 0.0, None, "none", [],
                           reason="롱폼 대본에서 겹치는 대목을 찾지 못했습니다.")

    best = candidates[0]
    audio_score = None
    method = "text"
    if audio_verify is not None:
        try:
            audio_score = float(audio_verify(best.start, best.end))
            method = "text+audio"
        except Exception as exc:      # 오디오 검증 실패가 매칭 전체를 막지 않는다
            audio_score = None
            method = "text"
            print(f"[숏츠매칭] 오디오 검증 실패: {exc}", flush=True)

    confidence = combine_confidence(best.text_score, audio_score)
    return MatchResult(
        start=clamp(best.start, longform_duration),
        end=clamp(best.end, longform_duration),
        confidence=confidence,
        text_score=round(best.text_score, 4),
        sequence_score=round(best.sequence, 4),
        audio_score=None if audio_score is None else round(audio_score, 4),
        method=method,
        candidates=candidates[:MAX_CANDIDATES],
    )


# ---------------------------------------------------------------- 상태 판정
# 임계값은 설정으로 바꿀 수 있어야 한다. 실제 영상으로 돌려 보기 전에는
# 어느 선이 맞는지 알 수 없어서, 기본값만 여기 두고 호출부에서 덮어쓴다.
DEFAULT_THRESHOLDS = {"confirm": 0.95, "review": 0.85, "check": 0.70}


def decide_status(confidence: float, thresholds: Optional[Dict[str, float]] = None) -> str:
    """신뢰도로 다음 상태를 정한다.

    확실하지 않으면 절대 확정하지 않는다. 애매한 값을 확정해 두면 학생이
    엉뚱한 지점부터 영상을 보게 되고, 그건 아무 연결도 없는 것보다 나쁘다.
    """
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update({k: float(v) for k, v in thresholds.items() if v is not None})
    if confidence >= t["confirm"]:
        return "completed"       # 자동 확정 가능
    if confidence >= t["review"]:
        return "needs_review"    # 검토 권장
    if confidence >= t["check"]:
        return "needs_review"    # 관리자 확인 필요
    return "needs_review"


def is_auto_confirmable(confidence: float, thresholds: Optional[Dict[str, float]] = None) -> bool:
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update({k: float(v) for k, v in thresholds.items() if v is not None})
    return confidence >= t["confirm"]


def segments_from_json(raw) -> List[Segment]:
    """저장해 둔 대본(JSON)을 Segment 로 되돌린다."""
    out: List[Segment] = []
    for item in raw or []:
        words = [
            Word(text=w.get("text") or w.get("word") or "",
                 start=float(w.get("start", 0.0)), end=float(w.get("end", 0.0)))
            for w in (item.get("words") or [])
        ]
        out.append(Segment(
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", 0.0)),
            text=item.get("text") or "",
            words=words,
        ))
    return out


def segments_to_json(segments: Sequence[Segment]) -> List[dict]:
    return [
        {
            "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text,
            "words": [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in s.words
            ],
        }
        for s in segments
    ]
