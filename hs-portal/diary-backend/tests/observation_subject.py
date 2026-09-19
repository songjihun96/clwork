"""과목별 관찰 기록(누가기록) 검사.

교사 관찰 기록에 과목을 강제로 붙이고, 그 과목 담당이 아니면 쓰지도
보지도 못하게 막았는지, 그리고 그 과목 기록만 모아 AI 결과물을 만들 때
다른 과목·다른 교사 기록이 섞이지 않는지가 핵심이다. AI는 실제로 부르지
않고 흉내 낸다.
"""
import os, sys, json, time
os.environ["DATABASE_URL"] = "sqlite:////tmp/obs_subj.db"; os.environ["SECRET_KEY"] = "x"

if os.path.exists("/tmp/obs_subj.db"):
    os.remove("/tmp/obs_subj.db")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from app import ai_jobs
from datetime import datetime
import requests

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

db = SessionLocal()
SCHOOL = 21
now = datetime.utcnow()

# 김교사: 프로그래밍 담당 + 담임. 최교사: 프로그래밍 공동 담당(같은 과목, 다른 교사).
# 박교사: 웹개발만 담당. 이교사: 담당 과목이 아예 없는 순수 담임.
kim = User(udj_user_id=301, email="kim2@t.kr", name="김교사", role=Role.teacher,
          school_id=SCHOOL, class_name="1반")
choi = User(udj_user_id=302, email="choi@t.kr", name="최교사", role=Role.teacher,
           school_id=SCHOOL, class_name="")
park = User(udj_user_id=303, email="park2@t.kr", name="박교사", role=Role.teacher,
           school_id=SCHOOL, class_name="")
lee = User(udj_user_id=304, email="lee@t.kr", name="이교사", role=Role.teacher,
          school_id=SCHOOL, class_name="2반")
hong = User(udj_user_id=401, email="hong2@t.kr", name="홍길동", role=Role.student,
           school_id=SCHOOL, school_name="근명고", class_name="1반",
           teacher_udj_id=301, verified=True)
# 이교사(담당 과목 없음)의 순수 담임 학생 — hong과는 별개로 둔다. 과목 담당이
# 전혀 없는 교사가 여전히 일반 관찰 기록을 쓸 수 있는지는 이 학생으로 본다.
minji = User(udj_user_id=402, email="minji@t.kr", name="민지", role=Role.student,
            school_id=SCHOOL, school_name="근명고", class_name="2반",
            teacher_udj_id=304, verified=True)
for u in (kim, choi, park, lee, hong, minji):
    db.add(u)
db.commit(); [db.refresh(u) for u in (kim, choi, park, lee, hong, minji)]

prog = SchoolSubject(school_id=SCHOOL, department="", grade=2, name="프로그래밍")
web = SchoolSubject(school_id=SCHOOL, department="", grade=2, name="웹개발")
db.add(prog); db.add(web); db.commit(); db.refresh(prog); db.refresh(web)
PROG_ID, WEB_ID, HONG_ID, MINJI_ID = prog.id, web.id, hong.id, minji.id

# 김교사·최교사는 프로그래밍을 함께 담당한다(공동 담당 시나리오). 박교사는 웹개발만.
# 이교사는 어떤 과목도 담당하지 않는다(순수 담임).
db.add(TeacherSubjectAssignment(teacher_id=kim.id, school_id=SCHOOL, subject_id=PROG_ID))
db.add(TeacherSubjectAssignment(teacher_id=choi.id, school_id=SCHOOL, subject_id=PROG_ID))
db.add(TeacherSubjectAssignment(teacher_id=park.id, school_id=SCHOOL, subject_id=WEB_ID))
db.commit()

KH = {"Authorization": f"Bearer {create_access_token(kim)}"}
CH = {"Authorization": f"Bearer {create_access_token(choi)}"}
PH = {"Authorization": f"Bearer {create_access_token(park)}"}
LH = {"Authorization": f"Bearer {create_access_token(lee)}"}
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


c.post("/api/ai/consent", json={"agreed": True}, headers=SH)

print("=== 0. 준비: 홍길동이 두 과목 수업일지를 제출해 각 과목 교사가 볼 수 있게 한다 ===")
def submit_lesson(headers, subject, text):
    r = c.post("/api/journals", json={"kind": "lesson", "entry_date": "2026-05-01",
        "title": subject, "subject": subject, "content": {"content": text}}, headers=headers)
    jid = r.json()["id"]
    c.post(f"/api/journals/{jid}/submit", headers=headers)
    return jid

submit_lesson(SH, "프로그래밍", "반복문 수업을 들었다.")
submit_lesson(SH, "웹개발", "폼 만들기 수업을 들었다.")

print("=== 1. 과목 없이 쓰기 — 담당 과목이 있으면 막힌다 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "content": "과목 없이 써봄"}, headers=KH)
chk("담당 과목 있는 교사는 과목 없이 못 씀 → 400", r.status_code == 400, str(r.json()))

print("=== 2. 담당 아닌 과목으로 쓰기 — 막힌다 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "subject_id": WEB_ID, "content": "웹개발이라고 우겨봄"}, headers=KH)
chk("김교사가 웹개발로 쓰기 → 403", r.status_code == 403, str(r.json()))

print("=== 3. 담당 과목으로 정상 작성 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "subject_id": PROG_ID,
    "content": "반복문 개념을 스스로 정리해 발표함"}, headers=KH)
chk("김교사가 프로그래밍으로 작성", r.status_code == 200, str(r.json()))
KIM_OBS_1 = r.json()["id"]
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "subject_id": PROG_ID,
    "content": "디버깅 중 오류 원인을 논리적으로 찾아냄"}, headers=KH)
chk("김교사가 프로그래밍으로 한 건 더 작성", r.status_code == 200)

print("=== 4. 담당 과목이 아예 없는 교사는 예전처럼 과목 없이 쓸 수 있다 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": MINJI_ID, "content": "등교 태도가 성실함"}, headers=LH)
chk("담당 과목 없는 이교사는 과목 없이 작성 가능", r.status_code == 200, str(r.json()))

print("=== 5. 공동 담당 교사(최교사)가 같은 과목으로 쓴 기록은 서로 안 보인다 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "subject_id": PROG_ID,
    "content": "최교사만 아는 비밀관찰내용XYZ"}, headers=CH)
chk("최교사도 프로그래밍으로 작성 가능", r.status_code == 200, str(r.json()))

rows_kim = c.get("/api/teacher/observations", params={"student_id": HONG_ID}, headers=KH).json()
chk("김교사 목록엔 최교사 기록이 안 보임",
    not any("비밀관찰내용XYZ" in row["content"] for row in rows_kim), str(rows_kim))
chk("김교사 목록엔 본인 기록 2건만", len(rows_kim) == 2, str(rows_kim))

print("=== 6. 과목 필터 ===")
rows_prog = c.get("/api/teacher/observations",
                  params={"student_id": HONG_ID, "subject_id": PROG_ID}, headers=KH).json()
chk("과목으로 좁혀도 본인 기록 2건 그대로", len(rows_prog) == 2, str(rows_prog))

print("=== 7. AI 결과물 — 담당 과목 아니면 막힌다 ===")
r = c.post(f"/api/students/{HONG_ID}/subjects/{WEB_ID}/ai-observation-note", headers=KH)
chk("김교사가 웹개발 결과물 요청 → 403", r.status_code == 403, str(r.json()))
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-observation-note", headers=PH)
chk("박교사가 프로그래밍 결과물 요청 → 403", r.status_code == 403, str(r.json()))

print("=== 8. AI 결과물 — 관찰 기록이 없는 과목은 거부 ===")
r = c.post(f"/api/students/{HONG_ID}/subjects/{WEB_ID}/ai-observation-note", headers=PH)
chk("박교사, 웹개발 관찰 기록 없어 400", r.status_code == 400, str(r.json()))

print("=== 9. AI 결과물 생성 — 본인이 쓴 이 과목 기록만 근거로 쓴다 ===")
requests.post = reply("반복문 개념을 스스로 정리하고 디버깅 과정에서 논리적 사고력을 보임.")
r = c.post(f"/api/students/{HONG_ID}/subjects/{PROG_ID}/ai-observation-note", headers=KH)
chk("요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], KH)
chk("생성 완료", job["status"] == "done", str(job)[:150])
requests.post = reply_verify_safe
chk("본인 기록(반복문) 들어감", any("반복문" in p for p in sent_prompts), "missing")
chk("본인 기록(디버깅) 들어감", any("디버깅" in p for p in sent_prompts), "missing")
chk("최교사의 비밀 기록 안 섞임", not any("비밀관찰내용XYZ" in p for p in sent_prompts), "leaked")
chk("담임 이교사의 등교 태도 기록 안 섞임", not any("등교 태도" in p for p in sent_prompts), "leaked")

records = c.get(f"/api/students/{HONG_ID}/ai-records", params={"type": "subject_special_note"},
                headers=KH).json()
chk("draft 저장됨", len(records) == 1 and records[0]["status"] == "draft", str(records))
chk("source_kind가 observation으로 표시됨", records[0]["source_kind"] == "observation", str(records))

print("=== 10. 학생·다른 학교 계정은 관찰 기록을 못 쓴다/못 본다 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": HONG_ID, "subject_id": PROG_ID, "content": "학생이 몰래 씀"}, headers=SH)
chk("학생 계정 차단", r.status_code == 403, str(r.status_code))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====" if all(OK) else
      f"\n===== {sum(OK)}/{len(OK)} 통과 (실패 있음) =====")
if not all(OK):
    sys.exit(1)
