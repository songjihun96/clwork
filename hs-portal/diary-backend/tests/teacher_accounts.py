"""선생님 계정(검색·권한부여·해제) — UDJ 화면에서 기록해로 옮겨온 기능.

계정 원본은 여전히 UDJ 뿐이라, 기록해는 매 요청을 그대로 UDJ partner API로
전달만 한다(journal_subjects_sync.py 와 같은 방식으로 requests.request 를
가짜로 바꿔 확인한다).
"""
import os, sys, json
os.environ["DATABASE_URL"] = "sqlite:////tmp/ta.db"; os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-secret"
os.environ["UDJ_API_BASE"] = "http://udj.test"

if os.path.exists("/tmp/ta.db"):
    os.remove("/tmp/ta.db")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
import requests

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

SCHOOL = 88
db = SessionLocal()
sch = User(udj_user_id=601, email="sc@t.kr", name="학교", role=Role.school, school_id=SCHOOL)
tea = User(udj_user_id=602, email="t@t.kr", name="교사", role=Role.teacher, school_id=SCHOOL)
stu = User(udj_user_id=603, email="s@t.kr", name="학생", role=Role.student, school_id=SCHOOL)
for u in (sch, tea, stu): db.add(u)
db.commit(); [db.refresh(u) for u in (sch, tea, stu)]
CH = {"Authorization": f"Bearer {create_access_token(sch)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
db.close()
c = TestClient(app)


class Res:
    def __init__(self, code, body):
        self.status_code = code; self._b = body
    def json(self): return self._b


calls = []
def fake_request(method, url, headers=None, timeout=None, **kw):
    calls.append((method, url, kw.get("params"), kw.get("json")))
    if url.endswith(f"/schools/{SCHOOL}/teachers") and method == "GET":
        return Res(200, [{"id": 999, "email": "new@t.kr", "name": "새선생",
                          "class_name": "2학년 3반", "is_active": True, "created_at": None}])
    if url.endswith(f"/schools/{SCHOOL}/teacher-candidates") and method == "GET":
        return Res(200, [{"id": 999, "email": "new@t.kr", "name": "새선생", "phone": "",
                          "role": "student", "class_name": "", "is_our_teacher": False,
                          "other_school": False}])
    if url.endswith(f"/schools/{SCHOOL}/teachers/grant") and method == "POST":
        return Res(200, {"ok": True, "teacher": {"id": 999, "name": "새선생"}})
    if f"/schools/{SCHOOL}/teachers/999" in url and method == "PUT":
        return Res(200, {"ok": True, "teacher": {"id": 999, "is_active": False}})
    if f"/schools/{SCHOOL}/teachers/999" in url and method == "DELETE":
        return Res(200, {"ok": True})
    return Res(404, {"detail": "not found"})
requests.request = fake_request


print("=== 1. 목록 ===")
r = c.get("/api/school/teacher-accounts", headers=CH)
chk("200", r.status_code == 200, str(r.status_code))
chk("UDJ 응답 그대로 나옴", r.json()[0]["name"] == "새선생", str(r.json()))
chk("학생은 못 씀", c.get("/api/school/teacher-accounts", headers=SH).status_code == 403)

print("=== 2. 검색 ===")
r = c.get("/api/school/teacher-accounts/search", params={"q": "새선생"}, headers=CH)
chk("200", r.status_code == 200)
chk("검색어가 UDJ 로 그대로 전달됨", calls[-1][2] == {"q": "새선생"}, str(calls[-1]))

print("=== 3. 권한 부여 ===")
r = c.post("/api/school/teacher-accounts/grant",
           json={"user_id": 999, "class_name": "2학년 3반"}, headers=CH)
chk("200", r.status_code == 200, str(r.json()))
chk("학교 id 로 UDJ 를 부름", f"/schools/{SCHOOL}/teachers/grant" in calls[-1][1], str(calls[-1]))
chk("user_id·class_name 이 그대로 전달됨",
    calls[-1][3] == {"user_id": 999, "class_name": "2학년 3반"}, str(calls[-1]))
chk("감사 로그 남음",
    SessionLocal().query(AuditLog).filter(AuditLog.action == "teacher_account.grant").count() == 1)

print("=== 4. 학급 변경·정지 ===")
r = c.put("/api/school/teacher-accounts/999", json={"is_active": False}, headers=CH)
chk("200", r.status_code == 200, str(r.json()))
chk("학생은 못 씀",
    c.put("/api/school/teacher-accounts/999", json={"is_active": False}, headers=SH).status_code == 403)

print("=== 5. 권한 해제 ===")
r = c.delete("/api/school/teacher-accounts/999", headers=CH)
chk("200", r.status_code == 200, str(r.json()))
chk("감사 로그 남음",
    SessionLocal().query(AuditLog).filter(AuditLog.action == "teacher_account.revoke").count() == 1)
chk("학생은 못 씀", c.delete("/api/school/teacher-accounts/999", headers=SH).status_code == 403)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
