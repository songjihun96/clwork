"""학생 소속 코드에 번호를 더한 것에 대한 검사.

기존 좌석코드(SeatCode) 흐름은 그대로 두고, 학생이 등록할 때 번호를
같이 넣을 수 있게 한 부분만 본다. 번호 없이 등록하는 예전 방식도
여전히 되는지 함께 본다.
"""
import os, sys, json
os.environ["DATABASE_URL"] = "sqlite:////tmp/en.db"; os.environ["SECRET_KEY"] = "x"

if os.path.exists("/tmp/en.db"):
    os.remove("/tmp/en.db")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from datetime import datetime, timedelta

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

db = SessionLocal()
SCHOOL = 5
now = datetime.utcnow()

tea = User(udj_user_id=301, email="t@t.kr", name="교사", role=Role.teacher,
          school_id=SCHOOL, class_name="1학년 2반", grade=1, department="")
s1 = User(udj_user_id=401, email="s1@t.kr", name="학생1", role=Role.student, school_id=SCHOOL)
s2 = User(udj_user_id=402, email="s2@t.kr", name="학생2", role=Role.student, school_id=SCHOOL)
s3 = User(udj_user_id=403, email="s3@t.kr", name="학생3", role=Role.student, school_id=SCHOOL)
s4 = User(udj_user_id=404, email="s4@t.kr", name="학생4", role=Role.student, school_id=SCHOOL)
for u in (tea, s1, s2, s3, s4):
    db.add(u)
db.commit(); [db.refresh(u) for u in (tea, s1, s2, s3, s4)]

db.add(SchoolSeat(school_id=SCHOOL, seats=50, started_at=now, expires_at=now + timedelta(days=300)))
db.commit()

TH = {"Authorization": f"Bearer {create_access_token(tea)}"}
S1H = {"Authorization": f"Bearer {create_access_token(s1)}"}
S2H = {"Authorization": f"Bearer {create_access_token(s2)}"}
S3H = {"Authorization": f"Bearer {create_access_token(s3)}"}
S4H = {"Authorization": f"Bearer {create_access_token(s4)}"}
db.close()
c = TestClient(app)

print("=== 1. 학년·반·학과가 드롭다운 값으로 정확히 저장된다 ===")
r = c.post("/api/school/seat-codes", json={"max_uses": 10, "grade": 1, "class_no": "2반",
    "department": "기계과"}, headers=TH)
chk("코드 생성", r.status_code == 200, str(r.json()))
code1 = r.json()["code"]
chk("학년 1", r.json()["grade"] == 1)
chk("반 문자열 형식 유지", r.json()["class_no"] == "2반")

print("=== 2. 학생 번호를 넣어 등록한다 ===")
r = c.post("/api/seat-codes/redeem", json={"code": code1, "student_no": 17}, headers=S1H)
chk("등록", r.status_code == 200 and r.json()["ok"], str(r.json()))
chk("배정 안내에 번호 포함", "17번" in r.json()["moved_to"], r.json()["moved_to"])

print("=== 3. 같은 반 같은 번호는 막는다 ===")
r = c.post("/api/seat-codes/redeem", json={"code": code1, "student_no": 17}, headers=S2H)
chk("중복 번호 거부", r.status_code == 409, str(r.status_code))

print("=== 4. 같은 반 다른 번호는 된다 ===")
r = c.post("/api/seat-codes/redeem", json={"code": code1, "student_no": 18}, headers=S2H)
chk("다른 번호는 등록됨", r.status_code == 200 and r.json()["ok"], str(r.json()))

print("=== 5. 다른 반의 같은 번호는 허용한다 ===")
r = c.post("/api/school/seat-codes", json={"max_uses": 10, "grade": 1, "class_no": "3반"},
    headers=TH)
code2 = r.json()["code"]
r = c.post("/api/seat-codes/redeem", json={"code": code2, "student_no": 17}, headers=S3H)
chk("다른 반 17번은 허용됨", r.status_code == 200 and r.json()["ok"], str(r.json()))

print("=== 6. 번호 없이 등록하는 예전 방식도 그대로 된다 ===")
r = c.post("/api/school/seat-codes", json={"max_uses": 5, "grade": 1, "class_no": "4반"},
    headers=TH)
code3 = r.json()["code"]
r = c.post("/api/seat-codes/redeem", json={"code": code3}, headers=S4H)
chk("번호 없이 등록", r.status_code == 200 and r.json()["ok"], str(r.json()))

print("=== 7. 저장된 소속을 확인한다 ===")
db = SessionLocal()
year = datetime.utcnow().year
rows = db.query(StudentEnrollment).filter(StudentEnrollment.school_id == SCHOOL,
                                          StudentEnrollment.academic_year == year).all()
chk("번호 넣은 학생 3명만 기록됨(번호 없이 등록한 학생4는 제외)", len(rows) == 3, str(len(rows)))
db.close()

print("=== 8. 학생은 학과·학년을 API로 직접 못 바꾼다 ===")
r = c.patch("/api/me", json={"department": "몰래바꾼학과"}, headers=S1H)
chk("학과 직접 수정 차단", r.status_code == 403, str(r.status_code))
r = c.patch("/api/me", json={"grade": 3}, headers=S1H)
chk("학년 직접 수정 차단", r.status_code == 403, str(r.status_code))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
