"""담당 과목·AI 세특/행동특성 검사.

과목별 기록 격리와 권한 우회 차단이 핵심이다. AI 는 실제로 부르지 않고
흉내 낸다(다른 AI 검사들과 같은 방식) — 여기서 보는 것은 "AI 가 잘 쓰는가"가
아니라 "서버가 어떤 기록을 AI 에게 넘기는가·누구를 막는가"다.
"""
import os, sys, json, time
os.environ["DATABASE_URL"] = "sqlite:////tmp/sn.db"; os.environ["SECRET_KEY"] = "x"

if os.path.exists("/tmp/sn.db"):
    os.remove("/tmp/sn.db")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from app import ai_jobs
from datetime import datetime, timedelta, date
import requests

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

db = SessionLocal()

SCHOOL = 9
now = datetime.utcnow()

# 김교사: 프로그래밍 담당 + 2학년 3반 담임. 박교사: 웹개발만 담당(담임 아님).
kim = User(udj_user_id=101, email="kim@t.kr", name="김교사", role=Role.teacher,
          school_id=SCHOOL, class_name="2학년 3반")
park = User(udj_user_id=102, email="park@t.kr", name="박교사", role=Role.teacher,
           school_id=SCHOOL, class_name="")
other_school_teacher = User(udj_user_id=103, email="etc@t.kr", name="다른학교교사",
                            role=Role.teacher, school_id=888, class_name="1학년 1반")
hong = User(udj_user_id=201, email="hong@t.kr", name="홍길동", role=Role.student,
           school_id=SCHOOL, school_name="근명고", class_name="2학년 3반",
           teacher_udj_id=101, verified=True)
for u in (kim, park, other_school_teacher, hong):
    db.add(u)
db.commit(); [db.refresh(u) for u in (kim, park, other_school_teacher, hong)]

prog = SchoolSubject(school_id=SCHOOL, department="", grade=2, name="프로그래밍")
web = SchoolSubject(school_id=SCHOOL, department="", grade=2, name="웹개발")
db.add(prog); db.add(web); db.commit(); db.refresh(prog); db.refresh(web)
PROG_ID, WEB_ID, HONG_ID = prog.id, web.id, hong.id

# 김교사는 프로그래밍만 담당한다. 웹개발은 박교사 담당이다.
db.add(TeacherSubjectAssignment(teacher_id=kim.id, school_id=SCHOOL, subject_id=PROG_ID))
db.add(TeacherSubjectAssignment(teacher_id=park.id, school_id=SCHOOL, subject_id=WEB_ID))
db.commit()

KH = {"Authorization": f"Bearer {create_access_token(kim)}"}
PH = {"Authorization": f"Bearer {create_access_token(park)}"}
EH = {"Authorization": f"Bearer {create_access_token(other_school_teacher)}"}
SH = {"Authorization": f"Bearer {create_access_token(hong)}"}
db.close()
c = TestClient(app)
ai_jobs.POLL_SECONDS = 0.2
ai_jobs.start()


def wait(job_id, headers, sec=8):
    for _ in range(int(sec * 10)):
        time.sleep(0.1)
        r = c.get(f"/api/ai/jobs/{job_id}", headers=headers).json()
        if r["status"] in ("done", "failed"):
            return r
    return {"status": "timeout"}


sent_prompts = []
class Res:
    def __init__(self, b): self.status_code = 200; self._b = b
    def json(self): return self._b
def reply(draft_text):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        sent_prompts.append(json["messages"][0]["content"])
        body = {"draft": draft_text, "facts_used": [], "warnings": []}
        return Res({"content": [{"type": "text", "text": J.dumps(body, ensure_ascii=False)}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}})
    return f
def reply_verify_safe(url, headers=None, json=None, timeout=None):
    import json as J
    body = {"safe": True, "issues": []}
    return Res({"content": [{"type": "text", "text": J.dumps(body, ensure_ascii=False)}],
                "usage": {"input_tokens": 1, "output_tokens": 1}})


print("=== 1. 준비: 학생이 과목별 수업일지·학교생활일지를 제출한다 ===")
def submit(headers, kind, subject, text):
    r = c.post("/api/journals", json={"kind": kind, "entry_date": "2026-05-01",
        "title": subject or kind, "subject": subject,
        "content": {"memorable" if kind == "diary" else "content": text}},
        headers=headers)
    jid = r.json()["id"]
    chk(f"작성({subject or kind})", r.status_code == 200)
    chk(f"제출({subject or kind})", c.post(f"/api/journals/{jid}/submit", headers=headers).status_code == 200)
    return jid

prog_jid = submit(SH, "lesson", "프로그래밍", "반복문으로 계산기를 만들었다. 오류를 스스로 찾아 고쳤다.")
web_jid = submit(SH, "lesson", "웹개발", "폼을 만들고 서버로 값을 보내는 것을 배웠다.")
diary_jid = submit(SH, "diary", "", "학급 행사 준비를 맡아 끝까지 책임지고 마쳤다.")

chk("수업일지에 subject_id 채워짐",
    c.get(f"/api/journals/{prog_jid}", headers=SH).json()["subject_id"] == PROG_ID)

print("=== 2. 동의 ===")
c.post("/api/ai/consent", json={"agreed": True}, headers=SH)

print("=== 3. 권한 — 담당 과목이 아니면 세특을 못 만든다 ===")
r = c.post(f"/api/students/{HONG_ID}/subjects/{WEB_ID}/ai-special-note", headers=KH)
chk("김교사가 웹개발 요청 → 403", r.status_code == 403, str(r.json()))
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-special-note", headers=PH)
chk("박교사가 프로그래밍 요청 → 403", r.status_code == 403, str(r.json()))

print("=== 4. 권한 — 담임이 아니면 행동특성을 못 만든다 ===")
r = c.post(f"/api/students/{HONG_ID}/ai-behavioral-characteristics", headers=PH)
chk("담임 아닌 박교사 → 403", r.status_code == 403, str(r.json()))

print("=== 5. 권한 — 다른 학교 교사는 아예 학생을 못 본다 ===")
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-special-note", headers=EH)
chk("다른 학교 교사 → 403", r.status_code == 403, str(r.json()))

print("=== 6. 세특 생성 — 이 과목 기록만 AI 에게 간다 ===")
requests.post = reply("반복문과 조건문을 활용해 계산기를 구현하고 스스로 오류를 찾아 해결함.")
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-special-note", headers=KH)
chk("요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], KH)
chk("생성 완료", job["status"] == "done", str(job)[:150])
requests.post = reply_verify_safe  # 검증 단계는 항상 안전하다고 답하게 둔다
# (실제로는 verify 가 draft 콜 다음에 한 번 더 불리므로, generate 콜에서 이미
#  잡힌 프롬프트로 격리 여부를 확인한다)
chk("웹개발 내용 안 섞임", not any("폼을 만들고" in p for p in sent_prompts), "leaked")
chk("프로그래밍 내용은 들어감", any("계산기" in p for p in sent_prompts), "missing")

records = c.get(f"/api/students/{HONG_ID}/ai-records", params={"type": "subject_special_note"},
                headers=KH).json()
chk("draft 상태로 저장됨", len(records) == 1 and records[0]["status"] == "draft", str(records))
DRAFT_ID = records[0]["id"]

print("=== 7. 초안 수정·확정 ===")
r = c.put(f"/api/ai-records/{DRAFT_ID}", json={"content": "교사가 고친 최종 문장."}, headers=KH)
chk("수정", r.status_code == 200 and r.json()["status"] == "reviewed", str(r.json()))
r = c.post(f"/api/ai-records/{DRAFT_ID}/confirm", headers=KH)
chk("확정", r.status_code == 200 and r.json()["status"] == "confirmed", str(r.json()))

print("=== 8. 재생성해도 확정본은 남는다 ===")
sent_prompts.clear()
requests.post = reply("다시 만든 초안.")
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-special-note", headers=KH)
job = wait(r.json()["job_id"], KH)
chk("재생성 완료", job["status"] == "done")
records = c.get(f"/api/students/{HONG_ID}/ai-records", params={"type": "subject_special_note"},
                headers=KH).json()
chk("확정본 그대로", any(x["id"] == DRAFT_ID and x["status"] == "confirmed"
                     and x["content"] == "교사가 고친 최종 문장." for x in records), str(records))
chk("새 draft 도 생김", len(records) == 2, str(records))

print("=== 9. 행동특성 — 담임의 학교생활일지만 쓴다 ===")
sent_prompts.clear()
requests.post = reply("학급 행사 준비에서 책임감 있는 모습을 보임.")
r = c.post(f"/api/students/{HONG_ID}/ai-behavioral-characteristics", headers=KH)
chk("담임 요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], KH)
chk("생성 완료", job["status"] == "done", str(job)[:150])
chk("수업일지 안 섞임", not any("계산기" in p or "폼을 만들고" in p for p in sent_prompts), "leaked")
chk("학교생활일지 내용 들어감", any("학급 행사" in p for p in sent_prompts), "missing")

print("=== 10. IDOR — 다른 교사의 초안을 못 고친다 ===")
r = c.put(f"/api/ai-records/{DRAFT_ID}", json={"content": "몰래 고치기"}, headers=PH)
chk("남의 초안 수정 차단", r.status_code == 404, str(r.status_code))
r = c.post(f"/api/ai-records/{DRAFT_ID}/confirm", headers=PH)
chk("남의 초안 확정 차단", r.status_code == 404, str(r.status_code))

print("=== 11. 담임이 아니어도 담당 과목이면 그 과목만큼은 볼 수 있다 ===")
r = c.get("/api/teacher/students", headers=PH).json()
chk("박교사 명단에 홍길동 뜸(웹개발 제출이 있어서)", any(s["id"] == HONG_ID for s in r), str(r))

sent_prompts.clear()
requests.post = reply("폼과 서버 통신 구조를 이해하고 직접 구현함.")
r = c.post(f"/api/students/{HONG_ID}/subjects/{WEB_ID}/ai-special-note", headers=PH)
chk("담임 아닌 박교사도 자기 과목(웹개발)은 요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], PH)
chk("생성 완료", job["status"] == "done", str(job)[:150])
chk("프로그래밍 내용 안 섞임", not any("계산기" in p for p in sent_prompts), "leaked")
chk("웹개발 내용은 들어감", any("폼을 만들고" in p for p in sent_prompts), "missing")

r = c.get("/api/teacher/journals", params={"student_id": HONG_ID}, headers=PH).json()
kinds_seen = {(x["kind"], x["subject_id"]) for x in r}
chk("박교사에겐 웹개발 수업일지만 보임",
    kinds_seen == {("lesson", WEB_ID)}, str(kinds_seen))

r = c.post(f"/api/students/{HONG_ID}/ai-behavioral-characteristics", headers=PH)
chk("담당 과목뿐인 박교사는 행동특성은 여전히 못 만듦(담임 전용)",
    r.status_code == 403, str(r.json()))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
