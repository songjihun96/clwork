"""학교·교사용 영상 원고 문서 생성 — 원고(school_narration.json)·타임라인과 문서가 어긋나지 않게 한다.

    python script/build_school_docs.py
    → docs/UDJ_SCHOOL_VIDEO_SCRIPT.md, docs/UDJ_TEACHER_VIDEO_SCRIPT.md
"""
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
DOCS = SRC.parents[1] / "docs"
NARR = json.loads((SRC / "script/school_narration.json").read_text(encoding="utf-8"))
TL = json.loads((SRC / "remotion/school_timeline.json").read_text(encoding="utf-8"))
CH = NARR["chapters"]
CH_NO = {k: f"{i + 1:02d}" for i, k in enumerate(CH)}
TITLE = {"intro": "서비스 소개", "request": "학교 계정 신청", "firstlogin": "첫 로그인", "overview": "학교 관리 화면",
         "profile": "학교 정보", "stats": "통계", "plan": "노출 플랜", "tasks": "업무 개요", "inquiry": "문의 관리",
         "events": "학교일정등록", "admission": "취업/진학 정보", "press": "특성화고신문 보도자료", "student": "학생 서비스", "connect": "학교와 학생의 연결",
         "flow": "도입 후 운영 흐름", "outro": "마무리"}
NAME = {"school_teacher_full": "통합본", "school_intro": "학교 도입 전체 흐름", "school_admin": "학교 관리자 기능",
        "teacher_guide": "담당 선생님 업무 가이드", "student_service": "학생 서비스"}


def tc(f):
    s = f / 60
    return f"{int(s // 60)}:{s % 60:05.2f}"


def table(ver):
    t = TL[ver]
    rows = ["| 시간 | 챕터 | 장면 | 나레이션 = 자막 |", "|---|---|---|---|"]
    for s in t["scenes"]:
        name = s.get("card") or TITLE.get(s["id"], s["id"])
        for l in s["lines"]:
            rows.append(f"| {tc(s['from'] + l['at'])} | {CH_NO[s['chapter']]} {CH[s['chapter']]} | {name} | {l['text']} |")
    return "\n".join(rows)


def tts_notes():
    out = []
    for sid, seg in NARR["segments"].items():
        for ln in seg["lines"]:
            if "tts" in ln:
                out.append(f"- {ln['text']}  \n  → TTS 발음: {ln['tts']}")
    return "\n".join(out)


head = """- 원본 데이터: `video/src/script/school_narration.json` (이 문서는 `python script/build_school_docs.py` 로 만든다)
- 자막 파일: `video/src/subtitles/udj_{버전}.srt`
- **나레이션과 자막은 같은 문장이다.** TTS 가 약칭·숫자를 바르게 읽도록 발음만 풀어 쓴 문장은 맨 아래에 따로 적었다.
- 음성: Microsoft Edge 신경망 TTS `ko-KR-SunHiNeural`, 속도 +6%. 학교 담당자에게 시스템을 설명하는 시연 말투.
- 쓰지 않은 표현: "놀라운", "혁신적인", "최고의", "모든 것을 해결", AI·자동화 효과 주장.
- 영상에서 직접 만든 부분(나레이션·자막·그래픽)은 약칭 UDJ 대신 "우리동네 직업계고"로만 부른다. 사이트 캡처 화면은 그대로.
- 선생님(teacher) 권한은 UDJ에서 없애기로 해서 선생님 전용 화면은 소개하지 않는다. 담당 선생님은 **학교 계정으로** 일한다.
"""

school = ["# UDJ 학교·교사용 기능 소개영상 — 나레이션·자막 원고", "", head]
for ver in ["school_teacher_full", "school_intro", "school_admin", "student_service"]:
    t = TL[ver]
    school += [f"## {NAME[ver]} — `video/{t['out']}` ({tc(t['frames'])})", "", table(ver), ""]
school += ["## TTS 발음 풀이", "", tts_notes(), ""]
(DOCS / "UDJ_SCHOOL_VIDEO_SCRIPT.md").write_text("\n".join(school), encoding="utf-8")

t = TL["teacher_guide"]
teacher = ["# UDJ 담당 선생님 업무 가이드 — 나레이션·자막 원고", "", head,
           "## 이 영상의 대상과 범위", "",
           "- 대상: 학교 계정을 맡아 실제로 입력·답변하는 선생님(진로·취업부, 입학 담당 등)",
           "- 범위: 학교 계정으로 로그인해 하는 일 — **문의 관리, 학교일정등록, 취업/진학 정보**, 그리고 그 정보가 학생 화면에 어떻게 보이는지",
           "- 제외: `/teacher` 선생님 화면(학급 학생·재학생 인증·학급 이관) — UDJ에서 없애기로 한 기능",
           "",
           f"## 담당 선생님 업무 가이드 — `video/{t['out']}` ({tc(t['frames'])})", "", table("teacher_guide"), "",
           "## 업무별 체크리스트 (영상 내용 요약)", "",
           "**문의 관리** — 문의 관리 탭 → 답변 대기 문의 확인 → 답변 입력(필요하면 파일 첨부) → [답변 저장 및 발송] → '메일 발송 완료' 확인 → 처리 끝난 문의 삭제. 새 문의 알림 받을 이메일을 등록해 두면 문의가 들어올 때 알림 메일을 받는다(접수 후 1년 지난 문의는 자동 파기).",
           "",
           "**학교일정등록** (베이직 플랜부터) — 일정 종류(학교 설명회/참가 행사) → 이름·시작일·시간·장소·신청 링크·설명 → [일정 추가] → 학교 일정 모아보기·학교 페이지·즐겨찾기 D-day 확인.",
           "",
           "**취업/진학 정보** (플래티넘 플랜 혜택) — 졸업 연도 선택 → 졸업생 기본 통계 → 주요대학 진학 데이터(또는 Excel 일괄 업로드) → 취업 데이터 → 주요 취업처 → 공개 설정 → [공개 화면 보기]로 확인. 입력하지 않은 값은 추정하지 않고 비워 둔다.",
           ""]
(DOCS / "UDJ_TEACHER_VIDEO_SCRIPT.md").write_text("\n".join(teacher), encoding="utf-8")
print("docs written")
