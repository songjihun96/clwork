"""이용권 코드 등록 — 학교가 아직 정해지지 않은 학생.

버그: 재학생 인증을 안 한 학생은 UDJ 가 학교를 빈 값으로 보내 기록해에도 학교가
없다. 그 학생이 선생님께 받은 코드를 넣으면 "우리 학교 코드가 아닙니다"로 막혔다.

확인할 것:
  (1) 학교가 없는 학생 → 코드의 학교로 소속이 정해지고 등록된다
  (2) 다음 로그인 때 UDJ 가 빈 학교를 보내도 그 소속이 지워지지 않는다
  (3) UDJ 가 다른 학교를 주면(인증 승인 등) 그때는 바뀐다
  (4) 인증을 신청만 한(미승인) 다른 학교 학생도 코드의 학교로 등록된다
  (5) 다른 학교로 인증까지 끝난 학생은 막는다(코드 유출 방지)
  (6) 없는 코드·꺼진 코드는 예전처럼 막는다
실행:  cd diary-backend && python tests/seat_code_school.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "diary_seat_code_school.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, SchoolSeat, SeatCode, SeatHolder, User  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
now = datetime.utcnow()
tea = User(udj_user_id=10, email="t@t.kr", name="김선생", role=Role.teacher,
           school_id=7, school_name="근명고등학교")
nosch = User(udj_user_id=11, email="a@t.kr", name="학교없음", role=Role.student)
pending = User(udj_user_id=12, email="b@t.kr", name="신청중", role=Role.student,
               school_id=9, school_name="다른고등학교", verified=False)
other = User(udj_user_id=13, email="c@t.kr", name="인증됨", role=Role.student,
             school_id=9, school_name="다른고등학교", verified=True)
db.add_all([tea, nosch, pending, other])
db.commit()
db.add(SchoolSeat(school_id=7, seats=10, started_at=now, expires_at=now + timedelta(days=300)))
code = SeatCode(school_id=7, code="QDB5-HSPU", product="essay", label="2학년 3반",
                grade=2, class_no="3반", max_uses=30, created_by=tea.id,
                expires_at=now + timedelta(days=300))
off = SeatCode(school_id=7, code="OFFF-CODE", product="essay", max_uses=30,
               created_by=tea.id, is_active=False, expires_at=now + timedelta(days=300))
db.add_all([code, off])
db.commit()
H = {u.email: {"Authorization": f"Bearer {create_access_token(u)}"} for u in (nosch, pending, other)}
NOSCH_ID, PENDING_ID = nosch.id, pending.id
db.close()
c = TestClient(app)

print("=== 1. 학교가 없는 학생 ===")
r = c.post("/api/seat-codes/redeem", json={"code": "QDB5-HSPU", "student_no": 11}, headers=H["a@t.kr"])
chk("등록된다", r.status_code == 200 and r.json().get("ok"), r.text)
s = SessionLocal()
u = s.get(User, NOSCH_ID)
chk("코드의 학교로 소속", u.school_id == 7, str(u.school_id))
chk("학교 이름도", u.school_name == "근명고등학교", u.school_name)
chk("좌석을 받음", s.query(SeatHolder).filter_by(user_id=NOSCH_ID, school_id=7).count() == 1)
chk("학년·반도 옮겨 담음", u.grade == 2 and u.class_name == "3반", f"{u.grade} {u.class_name}")

print("=== 2. 다음 로그인 때 UDJ 가 빈 학교를 보내도 ===")
u.apply_profile({"email": "a@t.kr", "name": "학교없음", "role": "student",
                 "school_id": None, "school_name": "", "verified": False})
s.commit()
chk("소속 유지", u.school_id == 7 and u.school_name == "근명고등학교", f"{u.school_id} {u.school_name}")
r = c.post("/api/seat-codes/redeem", json={"code": "QDB5-HSPU"}, headers=H["a@t.kr"])
chk("다시 넣으면 이미 있음", r.status_code == 200 and r.json().get("already"), r.text)

print("=== 3. UDJ 가 다른 학교를 주면 바뀐다 ===")
u.apply_profile({"email": "a@t.kr", "name": "학교없음", "role": "student",
                 "school_id": 8, "school_name": "새학교", "verified": True})
s.commit()
chk("바뀜", u.school_id == 8 and u.school_name == "새학교", f"{u.school_id} {u.school_name}")
s.close()

print("=== 4. 인증 신청만 한(미승인) 다른 학교 학생 ===")
r = c.post("/api/seat-codes/redeem", json={"code": "qdb5hspu"}, headers=H["b@t.kr"])
chk("등록된다(소문자·하이픈 없이 넣어도)", r.status_code == 200 and r.json().get("ok"), r.text)
s = SessionLocal()
chk("코드의 학교로 소속", s.get(User, PENDING_ID).school_id == 7)
s.close()

print("=== 5. 다른 학교로 인증까지 끝난 학생 ===")
r = c.post("/api/seat-codes/redeem", json={"code": "QDB5-HSPU"}, headers=H["c@t.kr"])
chk("막는다", r.status_code == 400 and "우리 학교 코드가 아닙니다" in r.json()["detail"], r.text)
chk("지금 소속을 알려 준다", "다른고등학교" in r.json()["detail"], r.text)

print("=== 6. 없는 코드 · 꺼진 코드 ===")
r = c.post("/api/seat-codes/redeem", json={"code": "ZZZZ-ZZZZ"}, headers=H["c@t.kr"])
chk("없는 코드", r.status_code == 400 and "쓸 수 없는 코드" in r.json()["detail"], r.text)
r = c.post("/api/seat-codes/redeem", json={"code": "OFFF-CODE"}, headers=H["c@t.kr"])
chk("꺼진 코드", r.status_code == 400 and "쓸 수 없는 코드" in r.json()["detail"], r.text)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
