"""학교 계정 발급 신청 검사.

확인할 것:
  (1) 로그인 없이 신청할 수 있고, 동의 없이는 못 한다
  (2) 목록에 없는 학교는 이름을 직접 적어도 접수된다
  (3) 관리자만 신청서를 보고 처리할 수 있다 (개인정보가 들어 있다)
  (4) 승인하면 학교 계정이 생기고, 임시 비밀번호로 로그인되며,
      첫 로그인에서 비밀번호를 바꾸라고 표시된다
  (5) 두 번 승인·중복 이메일·학교 미연결 같은 실수를 막는다
  (6) 이미 계정이 있는 학교는 막지 않되 관리자 화면에 알려 준다
  (7) 보관 기간이 지난 신청서는 파기된다
실행:  cd backend && python tests/school_requests.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "udj_school_req_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
# 메일은 설정하지 않는다 — 발송 실패해도 승인은 되어야 한다(전화로 알려주는 길).
for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
    os.environ.pop(k, None)
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import school_requests as sr  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Coed, Plan, Role, School, SchoolAccountRequest, User)  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
S1 = School(name="신청고등학교", category="특성화고", region="경기", address="수원",
            coed=Coed.coed, plan=Plan.free, is_visible=True, phone="031-1")
S2 = School(name="이미있는고등학교", category="특성화고", region="서울", address="서울",
            coed=Coed.coed, plan=Plan.free, is_visible=True, phone="02-1")
db.add_all([S1, S2])
db.commit()
db.refresh(S1)
db.refresh(S2)
SID1, SID2 = S1.id, S2.id
admin = User(email="admin@t.kr", password_hash=hash_password("p1234567"), name="관리자",
             role=Role.admin)
stu = User(email="stu@t.kr", password_hash=hash_password("p1234567"), name="학생",
           role=Role.student)
old = User(email="old@t.kr", password_hash=hash_password("p1234567"), name="기존 학교계정",
           role=Role.school, school_id=SID2)
db.add_all([admin, stu, old])
db.commit()
[db.refresh(u) for u in (admin, stu, old)]
HA = {"Authorization": f"Bearer {create_access_token(admin)}"}
HS = {"Authorization": f"Bearer {create_access_token(stu)}"}
db.close()
c = TestClient(app)

FORM = {
    "school_id": SID1, "school_name": "신청고등학교", "manager_name": "김담당",
    "manager_position": "교무부장", "manager_phone": "010-1234-5678",
    "manager_email": "office@school1.kr", "school_phone": "031-000-0000",
    "call_time": "평일 오후 2~4시", "privacy_consent": True,
}

print("=== 1. 신청 접수 ===")
r = c.get("/api/privacy/school-account-request")
chk("개인정보 안내문 제공", r.status_code == 200 and "purpose" in r.json())
r = c.post("/api/school-account-requests", json={**FORM, "privacy_consent": False})
chk("동의 없으면 거부", r.status_code == 422, r.text[:120])
r = c.post("/api/school-account-requests", json={**FORM, "manager_email": "x"})
chk("이메일 형식 검사", r.status_code == 422)
r = c.post("/api/school-account-requests", json={**FORM, "manager_phone": "없음"})
chk("전화번호 형식 검사", r.status_code == 422, r.text[:120])
r = c.post("/api/school-account-requests", json={**FORM, "school_id": 99999})
chk("없는 학교 id 는 404", r.status_code == 404)
r = c.post("/api/school-account-requests", json=FORM)
chk("로그인 없이 접수 200", r.status_code == 200, r.text[:200])
RID = r.json()["id"]
chk("접수 응답에 개인정보가 없다",
    set(r.json()) == {"ok", "id", "message"}, str(r.json()))
r = c.post("/api/school-account-requests", json=FORM)
chk("같은 이메일 대기 중이면 409", r.status_code == 409, str(r.status_code))
r = c.post("/api/school-account-requests", json={
    **FORM, "school_id": None, "school_name": "목록에없는고등학교",
    "manager_email": "office@school9.kr"})
chk("목록에 없는 학교는 이름만으로 접수", r.status_code == 200, r.text[:150])
RID_FREE = r.json()["id"]

print("=== 2. 신청서는 관리자만 본다 ===")
chk("비로그인 목록 401", c.get("/api/admin/school-account-requests").status_code == 401)
chk("학생 목록 403", c.get("/api/admin/school-account-requests", headers=HS).status_code == 403)
chk("학생 승인 시도 403",
    c.post(f"/api/admin/school-account-requests/{RID}/approve", headers=HS).status_code == 403)
r = c.get("/api/admin/school-account-requests", headers=HA)
chk("관리자 목록 200", r.status_code == 200, r.text[:150])
data = r.json()
chk("처리 대기 2건", data["open_count"] == 2, str(data["open_count"]))
one = next(x for x in data["items"] if x["id"] == RID)
chk("담당자 정보가 관리자에게는 보인다",
    one["manager_phone"] == "010-1234-5678" and one["manager_email"] == "office@school1.kr")
chk("학교가 연결됨", one["school_matched"] is True and one["school_id"] == SID1)
free = next(x for x in data["items"] if x["id"] == RID_FREE)
chk("직접 적은 학교는 미연결 표시", free["school_matched"] is False)

print("=== 3. 상태·메모 ===")
r = c.patch(f"/api/admin/school-account-requests/{RID}", headers=HA,
            json={"status": "called", "admin_note": "담당자와 통화 완료"})
chk("통화 완료로 변경", r.status_code == 200 and r.json()["status"] == "called", r.text[:150])
chk("상태 라벨", r.json()["status_label"] == "통화 완료")
r = c.patch(f"/api/admin/school-account-requests/{RID}", headers=HA, json={"status": "approved"})
chk("상태 바꾸기로는 승인 못 함", r.status_code == 422, r.text[:150])
r = c.patch(f"/api/admin/school-account-requests/{RID}", headers=HA, json={"status": "몰라"})
chk("모르는 상태 거부", r.status_code == 422)

print("=== 4. 학교 미연결 신청은 승인 전에 연결해야 한다 ===")
r = c.post(f"/api/admin/school-account-requests/{RID_FREE}/approve", headers=HA)
chk("학교 미연결이면 승인 거부", r.status_code == 422 and "학교" in r.text, r.text[:150])
r = c.post(f"/api/admin/school-account-requests/{RID_FREE}/link-school",
           params={"school_id": SID1}, headers=HA)
chk("학교 연결", r.status_code == 200 and r.json()["school_id"] == SID1, r.text[:150])

print("=== 5. 승인 → 계정 생성 · 메일 실패해도 승인은 된다 ===")
r = c.post(f"/api/admin/school-account-requests/{RID}/approve", headers=HA)
chk("승인 200", r.status_code == 200, r.text[:200])
res = r.json()
chk("임시 비밀번호를 돌려준다(전화로 알려줄 수 있게)", len(res.get("temp_password", "")) >= 10)
chk("메일 미설정이면 mail_sent=False + 이유", res["mail_sent"] is False and res["mail_error"])
PW = res["temp_password"]
r = c.post("/api/auth/login", json={"email": "office@school1.kr", "password": PW})
chk("임시 비밀번호로 로그인된다", r.status_code == 200, r.text[:150])
me = r.json()
chk("학교 계정으로 만들어졌다", me["user"]["role"] == "school", str(me.get("user"))[:150])
chk("비밀번호를 바꾸라고 표시된다", me["user"].get("must_change_password") is True,
    str(me["user"])[:200])
db = SessionLocal()
acc = db.query(User).filter(User.email == "office@school1.kr").first()
chk("학교에 연결되었다", acc.school_id == SID1)
chk("담당자 연락처가 계정에 복사됨", acc.phone == "010-1234-5678")
db.close()
r = c.post(f"/api/admin/school-account-requests/{RID}/approve", headers=HA)
chk("두 번 승인하면 409", r.status_code == 409, str(r.status_code))
r = c.patch(f"/api/admin/school-account-requests/{RID}", headers=HA, json={"status": "rejected"})
chk("승인된 건은 상태를 되돌릴 수 없다", r.status_code == 409)

print("=== 6. 이미 계정이 있는 학교 ===")
r = c.post("/api/school-account-requests", json={
    **FORM, "school_id": SID2, "school_name": "이미있는고등학교",
    "manager_email": "office@school2.kr"})
chk("이미 계정이 있어도 접수는 된다", r.status_code == 200, r.text[:150])
RID2 = r.json()["id"]
r = c.get("/api/admin/school-account-requests", headers=HA)
row2 = next(x for x in r.json()["items"] if x["id"] == RID2)
chk("관리자 화면에 기존 계정을 알려 준다",
    len(row2["existing_accounts"]) == 1 and row2["existing_accounts"][0]["email"] == "old@t.kr",
    str(row2["existing_accounts"]))
r = c.post("/api/school-account-requests", json={
    **FORM, "school_id": SID2, "school_name": "이미있는고등학교",
    "manager_email": "old@t.kr"})
chk("이미 가입된 이메일도 접수는 된다(승인 때 막는다)", r.status_code == 200)
RID3 = r.json()["id"]
r = c.post(f"/api/admin/school-account-requests/{RID3}/approve", headers=HA)
chk("가입된 이메일은 승인 거부", r.status_code == 409 and "이미 가입" in r.text, r.text[:150])

print("=== 7. 보관 기간이 지난 신청서 파기 ===")
db = SessionLocal()
old_row = SchoolAccountRequest(
    school_id=SID1, school_name="옛날고", manager_name="옛담당", manager_phone="010-0000-0000",
    manager_email="old-req@t.kr", privacy_consent=True, status="rejected",
    created_at=datetime.utcnow() - timedelta(days=sr.REJECTED_RETENTION_DAYS + 1))
keep_row = SchoolAccountRequest(
    school_id=SID1, school_name="최근고", manager_name="최근담당", manager_phone="010-0000-0001",
    manager_email="new-req@t.kr", privacy_consent=True, status="rejected",
    created_at=datetime.utcnow() - timedelta(days=3))
db.add_all([old_row, keep_row])
db.commit()
db.close()
r = c.get("/api/admin/school-account-requests", headers=HA)
emails = [x["manager_email"] for x in r.json()["items"]]
chk("기간 지난 반려 건은 지워짐", "old-req@t.kr" not in emails, str(emails))
chk("최근 건은 남아 있음", "new-req@t.kr" in emails)

print("=== 8. 삭제 ===")
r = c.delete(f"/api/admin/school-account-requests/{RID2}", headers=HA)
chk("관리자 삭제 200", r.status_code == 200)
chk("학생은 삭제 불가",
    c.delete(f"/api/admin/school-account-requests/{RID3}", headers=HS).status_code == 403)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
