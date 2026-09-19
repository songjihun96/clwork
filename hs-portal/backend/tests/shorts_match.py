"""숏츠 → 롱폼 구간 찾기 검사.

실제 영상 없이 돌린다. 매칭 엔진은 대본(낱말+시각)만 입력으로 받으므로,
STT 결과를 흉내 낸 자료로 알고리즘 자체를 검증할 수 있다. 영상 파일이
있어야만 검사할 수 있게 만들면 아무도 안 돌리게 된다.

지시서 §35 의 편집 상황(자막·인트로·문장 삭제·속도 변경 등)이 STT 대본에
어떻게 나타나는지를 흉내 내어, 그런 경우에도 구간을 찾는지 본다.
"""
import os
import sys

sys.path.insert(0, ".")
from app.shorts_match import (  # noqa: E402
    Segment, Word, combine_confidence, decide_status, find_candidates,
    is_auto_confirmable, match, segments_from_json, segments_to_json,
)

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


def words(text: str, start: float, per: float = 0.4):
    """낱말마다 시각을 붙인 Segment 를 만든다(STT 흉내)."""
    parts = text.split()
    ws = [Word(text=w, start=start + i * per, end=start + (i + 1) * per)
          for i, w in enumerate(parts)]
    return Segment(start=start, end=start + len(parts) * per, text=text, words=ws)


# 1시간짜리 특강을 흉내 낸 롱폼 대본. 서로 다른 대목이 여러 개 있어야
# "엉뚱한 데를 짚지 않는지"를 볼 수 있다.
LONG = [
    words("안녕하세요 오늘은 취업 특강을 시작하겠습니다", 0.0),
    words("먼저 자기소개서 이야기부터 해보겠습니다", 12.0),
    words("자기소개서는 지원 동기를 구체적으로 적는 것이 중요합니다", 30.0),
    words("면접에서 가장 중요한 것은 자신감입니다", 204.0),
    words("그리고 두 번째로 중요한 것은 성실한 태도입니다", 216.0),
    words("취업 준비는 이학년 겨울방학부터 시작하는 것이 좋습니다", 522.0),
    words("현장실습은 학교와 충분히 상의한 뒤 결정하세요", 921.0),
    words("면접에서 하면 안 되는 행동은 지각과 무성의한 답변입니다", 1623.0),
    words("마지막으로 여러분의 취업을 응원하겠습니다", 3120.0),
]

print("=== 1. 그대로 잘린 숏츠 ===")
short = [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)]
r = match(LONG, short, longform_duration=3600)
chk("구간을 찾음", r.found, r.reason)
chk("시작이 204초 근처", r.found and abs(r.start - 204.0) < 1.5, str(r.start))
chk("끝이 206초 근처", r.found and abs(r.end - 206.0) < 1.5, str(r.end))
chk("신뢰도 높음", r.confidence >= 0.95, str(r.confidence))
chk("자동 확정 가능", is_auto_confirmable(r.confidence), str(r.confidence))

print("=== 2. 다른 대목은 다른 구간으로 ===")
for text, want in [
    ("취업 준비는 이학년 겨울방학부터 시작하는 것이 좋습니다", 522.0),
    ("자기소개서는 지원 동기를 구체적으로 적는 것이 중요합니다", 30.0),
    ("면접에서 하면 안 되는 행동은 지각과 무성의한 답변입니다", 1623.0),
]:
    rr = match(LONG, [words(text, 0.0)], longform_duration=3600)
    chk(f"{text[:14]}… → {want}초", rr.found and abs(rr.start - want) < 1.5,
        str(rr.start if rr.found else rr.reason))

print("=== 3. 앞뒤에 인트로·아웃트로가 붙은 숏츠 ===")
short = [
    words("우리동네 직업계고 채널입니다 구독 부탁드려요", 0.0),
    words("면접에서 가장 중요한 것은 자신감입니다", 3.0),
    words("다음 영상에서 만나요", 6.0),
]
r = match(LONG, short, longform_duration=3600)
chk("인트로가 있어도 본문 구간을 짚음", r.found and abs(r.start - 204.0) < 2.0,
    str(r.start if r.found else r.reason))
# 인트로·아웃트로는 롱폼에 없으므로 커버리지가 떨어진다. 그래서 자동 확정이
# 아니라 검토로 내려가는 게 맞다 — 억지로 확정하면 잘못된 구간을 굳힌다.
chk("커버리지가 떨어져 확정까지는 아님", not is_auto_confirmable(r.confidence),
    str(r.confidence))

print("=== 4. 중간 문장이 빠진 숏츠 ===")
short = [
    words("면접에서 가장 중요한 것은 자신감입니다", 0.0),
    words("그리고 두 번째로 중요한 것은 성실한 태도입니다", 2.5),
]
r = match(LONG, short, longform_duration=3600)
chk("두 문장에 걸친 구간을 잡음", r.found and abs(r.start - 204.0) < 2.0, str(r.start))
chk("끝이 두 번째 문장까지 늘어남", r.found and r.end > 216.0, str(r.end))

print("=== 5. STT 가 조금 다르게 받아 적은 경우 ===")
# '자신감입니다' -> '자신감 입니다' 처럼 띄어쓰기가 갈리는 일이 흔하다.
short = [words("면접에서 가장 중요한 것은 자신감 입니다", 0.0)]
r = match(LONG, short, longform_duration=3600)
chk("띄어쓰기가 달라도 찾음", r.found and abs(r.start - 204.0) < 2.0,
    str(r.start if r.found else r.reason))

print("=== 6. 롱폼에 없는 내용은 확정하지 않는다 ===")
short = [words("오늘 점심 메뉴는 김치찌개와 계란말이였습니다", 0.0)]
r = match(LONG, short, longform_duration=3600)
chk("없는 내용은 신뢰도가 낮다", r.confidence < 0.70, str(r.confidence))
chk("자동 확정하지 않는다", not is_auto_confirmable(r.confidence))
chk("상태는 needs_review", decide_status(r.confidence) == "needs_review",
    decide_status(r.confidence))

print("=== 7. 낱말 시각이 없는 STT(문장 단위)도 동작 ===")
long_plain = [Segment(start=s.start, end=s.end, text=s.text, words=[]) for s in LONG]
r = match(long_plain, [Segment(start=0, end=2, text="면접에서 가장 중요한 것은 자신감입니다")],
          longform_duration=3600)
chk("문장 단위 시각만으로도 찾음", r.found and abs(r.start - 204.0) < 3.0,
    str(r.start if r.found else r.reason))

print("=== 8. 영상 길이를 벗어나지 않는다 ===")
r = match(LONG, [words("마지막으로 여러분의 취업을 응원하겠습니다", 0.0)],
          longform_duration=3121.0)
chk("끝 시각이 길이 안쪽", r.found and r.end <= 3121.0, str(r.end))

print("=== 9. 후보를 여러 개 돌려준다 ===")
cands = find_candidates(LONG, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)])
chk("후보가 하나 이상", len(cands) >= 1, str(len(cands)))
chk("1등이 가장 높은 점수",
    all(cands[0].text_score >= c.text_score for c in cands))

print("=== 10. 오디오 점수 합산 ===")
r_no = match(LONG, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)])
chk("오디오 없으면 audio_score 는 None", r_no.audio_score is None)
chk("오디오 없어도 방식은 text", r_no.method == "text", r_no.method)
r_hi = match(LONG, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)],
             audio_verify=lambda s, e: 0.99)
chk("오디오 검증하면 방식이 text+audio", r_hi.method == "text+audio")
chk("오디오 점수가 반영됨", r_hi.audio_score == 0.99)
# 숏츠에는 배경음악·효과음이 깔려 제대로 잘라낸 것도 상관도가 0 에 가깝게
# 나온다. 그걸 감점으로 쓰면 텍스트가 잘 맞은 매칭까지 '확인 필요'로 떨어진다.
# 그래서 낮은 오디오 점수는 '틀렸다'가 아니라 '알 수 없다'로 본다.
r_lo = match(LONG, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)],
             audio_verify=lambda s, e: 0.0)
chk("오디오가 낮아도 텍스트 점수를 깎지 않는다",
    abs(r_lo.confidence - r_no.confidence) < 0.0001,
    f"{r_lo.confidence} vs {r_no.confidence}")
chk("낮은 오디오 점수도 화면에는 보여준다", r_lo.audio_score == 0.0)
chk("오디오가 높으면 그보다 높다", r_hi.confidence >= r_lo.confidence,
    f"{r_hi.confidence} vs {r_lo.confidence}")
# 오디오 검증이 터져도 매칭 자체는 살아 있어야 한다.
def _boom(s, e):
    raise RuntimeError("ffmpeg 없음")
r_err = match(LONG, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)], audio_verify=_boom)
chk("오디오 검증이 실패해도 구간은 나온다", r_err.found and r_err.audio_score is None)

print("=== 11. 신뢰도 합산 규칙 ===")
chk("오디오 없으면 텍스트 점수 그대로", combine_confidence(0.9, None) == 0.9)
chk("오디오가 높으면 올라간다", combine_confidence(0.9, 1.0) > 0.9)
chk("오디오가 낮으면 텍스트 점수 그대로(깎지 않음)",
    combine_confidence(0.9, 0.0) == 0.9, str(combine_confidence(0.9, 0.0)))
chk("애매한 오디오도 깎지 않음", combine_confidence(0.9, 0.4) == 0.9)
chk("확실한 오디오는 반영", combine_confidence(0.9, 0.95) > 0.9)
chk("0~1 을 벗어나지 않는다",
    0.0 <= combine_confidence(1.0, 1.0) <= 1.0 and combine_confidence(0.0, 0.0) >= 0.0)

print("=== 12. 임계값은 바꿀 수 있다 ===")
chk("기본값에서 0.9 는 확정 아님", not is_auto_confirmable(0.9))
chk("임계값을 낮추면 확정", is_auto_confirmable(0.9, {"confirm": 0.85}))

print("=== 13. 대본 저장/복원 ===")
js = segments_to_json(LONG)
back = segments_from_json(js)
chk("왕복해도 문장 수 유지", len(back) == len(LONG))
chk("왕복해도 낱말 시각 유지",
    abs(back[3].words[0].start - LONG[3].words[0].start) < 0.01)
r2 = match(back, [words("면접에서 가장 중요한 것은 자신감입니다", 0.0)], longform_duration=3600)
chk("복원한 대본으로도 같은 구간", r2.found and abs(r2.start - 204.0) < 1.5, str(r2.start))

print("=== 14. 빈 입력 ===")
chk("롱폼 대본이 없으면 못 찾음", not match([], [words("아무 말", 0.0)]).found)
chk("숏츠 대본이 없으면 못 찾음", not match(LONG, []).found)

print("=== 16. ffmpeg 가 없어도 죽지 않는다 ===")
from app import media   # noqa: E402

chk("ffmpeg 없으면 길이 못 잼", media.probe_duration("없는파일.mp4") is None)
chk("ffmpeg 없으면 오디오 곡선 None", media.energy_envelope("없는파일.mp4") is None)
chk("ffmpeg 없으면 검증기도 None", media.make_audio_verifier("a.mp4", "b.mp4") is None)
okx, errx = media.extract_audio("없는파일.mp4", "out.mp3")
chk("오디오 추출 실패는 사유를 준다", not okx and bool(errx), errx)

print("=== 17. 오디오 곡선 대조 ===")
same = [0.0, 5.0, 9.0, 3.0, 0.5, 7.0, 8.0, 1.0]
chk("같은 곡선은 1.0", media.envelope_similarity(same, same) > 0.99,
    str(media.envelope_similarity(same, same)))
chk("밀린 곡선도 찾아낸다",
    media.envelope_similarity(same, [0.0, 0.0] + same) > 0.99,
    str(media.envelope_similarity(same, [0.0, 0.0] + same)))
# 인트로가 붙어 한참 밀려 있어도 제자리를 찾아야 한다. 예전에는 3초까지만
# 밀어 봐서, 앞에 인트로가 붙은 숏츠가 0점을 받았다.
_far = [0.0] * 60 + same + [0.0] * 20
chk("많이 밀려 있어도 찾아낸다", media.envelope_similarity(same, _far) > 0.99,
    str(media.envelope_similarity(same, _far)))
chk("무관한 곡선은 낮다",
    media.envelope_similarity(same, [9.0, 1.0, 2.0, 8.0, 0.1, 3.0, 6.0, 4.0]) < 0.8)
chk("빈 입력은 0", media.envelope_similarity([], same) == 0.0)

print("=== 19. 한국어 표기 흔들림을 견디는가 ===")
# STT 마다 띄어쓰기와 조사가 갈린다. 낱말 단위로 견주면 그 차이 하나에
# 낱말이 통째로 틀린 것이 되어, 제대로 잘라 낸 숏츠가 0.74 점을 받았다.
# 글자 단위로 견주면 그 차이가 사라진다.
for label, text in [
    ("띄어쓰기 다름", "면접에서 가장 중요한 것은 자신감 입니다"),
    ("조사 붙임", "면접에서 가장 중요한것은 자신감입니다"),
    ("전부 붙여 씀", "면접에서가장중요한것은자신감입니다"),
    ("앞이 잘림", "가장 중요한 것은 자신감입니다"),
    ("끝에 군더더기", "면접에서 가장 중요한 것은 자신감 입니다요"),
]:
    rr = match(LONG, [words(text, 0.0)], longform_duration=3600)
    chk(f"{label} → 204초", rr.found and abs(rr.start - 204.0) < 2.0,
        str(rr.start if rr.found else rr.reason))
    chk(f"{label} 자동 확정", is_auto_confirmable(rr.confidence), str(rr.confidence))

# 글자로 봐도 엉뚱한 데를 짚으면 안 된다.
rr = match(LONG, [words("현장실습은 학교와 충분히 상의한 뒤 결정하세요", 0.0)],
           longform_duration=3600)
chk("다른 대목은 여전히 제자리", rr.found and abs(rr.start - 921.0) < 2.0,
    str(rr.start if rr.found else None))

# 조각난 우연 일치가 구간 시작을 앞으로 끌어당기면 안 된다.
# ("니다" 같은 두세 글자가 영상 곳곳에 있어서, 예전엔 204초가 0.8초로 잡혔다)
intro = [
    words("우리동네 직업계고 채널입니다 구독 부탁드려요", 0.0),
    words("면접에서 가장 중요한 것은 자신감입니다", 3.0),
]
rr = match(LONG, intro, longform_duration=3600)
chk("짧은 우연 일치에 끌려가지 않는다", rr.found and rr.start > 100,
    str(rr.start if rr.found else None))

print("=== 20. 글자 보기 변환 ===")
from app.shorts_match import char_view   # noqa: E402
cs, owner = char_view(["면접에서", "가장"])
chk("띄어쓰기가 사라진다", cs == "면접에서가장", cs)
chk("글자마다 낱말 자리를 기억한다", owner == [0, 0, 0, 0, 1, 1], str(owner))
chk("빈 입력", char_view([]) == ("", []))

print("=== 21. 여러 문장짜리 숏츠도 첫 문장부터 잡는가 ===")
# 창(window)을 떠서 견주던 시절, 그 창이 어긋나면 숏츠 앞부분이 잘려 나가
# 구간 시작이 뒤로 밀렸다. 학생이 "전체 영상 보기"를 누르면 숏츠 내용의
# 절반쯤이 이미 지나간 자리에서 재생됐다. 지금은 롱폼 전체를 한 번에 맞춘다.
LONG2 = [
    words("안녕하세요 오늘은 취업 특강을 시작하겠습니다", 0.0),
    words("자기소개서는 지원 동기를 구체적으로 적는 것이 중요합니다", 30.0),
    words("면접에서 가장 중요한 것은 자신감입니다", 204.0),
    words("왜냐하면 면접관은 여러분의 태도를 먼저 보기 때문입니다", 210.0),
    words("그래서 목소리를 크게 내고 눈을 마주치는 연습을 해야 합니다", 218.0),
    words("두 번째로 중요한 것은 성실한 태도입니다", 228.0),
    words("취업 준비는 이학년 겨울방학부터 시작하는 것이 좋습니다", 522.0),
]
body = [
    words("면접에서 가장 중요한 것은 자신감입니다", 0.0),
    words("왜냐하면 면접관은 여러분의 태도를 먼저 보기 때문입니다", 6.0),
    words("그래서 목소리를 크게 내고 눈을 마주치는 연습을 해야 합니다", 14.0),
]
r = match(LONG2, body, longform_duration=3600)
chk("첫 문장 시작에서 시작한다", r.found and abs(r.start - 204.0) < 0.5,
    str(r.start if r.found else r.reason))
chk("끝이 마지막 문장까지 간다", r.found and r.end > 218.0, str(r.end))
chk("자동 확정", is_auto_confirmable(r.confidence), str(r.confidence))

# 앞 문장이 STT 로 조금 다르게 적혀도 시작이 밀리면 안 된다
body2 = [words("면접에서 가장 중요한것은 자신감 입니다", 0.0)] + body[1:]
r2 = match(LONG2, body2, longform_duration=3600)
chk("앞 문장 표기가 달라도 시작 유지", r2.found and abs(r2.start - 204.0) < 0.5,
    str(r2.start if r2.found else r2.reason))

print("=== 22. 흩어진 우연 일치가 한 구간으로 뭉치지 않는가 ===")
# 한 글자짜리 일치들이 다리를 놓아 "0.8초 ~ 1623초" 같은 구간이 나왔었다.
odd = [words("가나다라 마바사 아자차카 타파하", 0.0)]
r3 = match(LONG2, odd, longform_duration=3600)
chk("관계없는 내용은 구간이 안 벌어진다",
    (not r3.found) or (r3.end - r3.start) < 120, 
    f"{r3.start} ~ {r3.end}" if r3.found else "못 찾음")
chk("신뢰도도 낮다", r3.confidence < 0.7, str(r3.confidence))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
