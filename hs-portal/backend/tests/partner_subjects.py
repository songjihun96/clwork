"""기록해가 학과·과목을 실시간으로 받아가는 partner API 검사."""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/ps.db"; os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-secret"

if os.path.exists("/tmp/ps.db"):
    os.remove("/tmp/ps.db")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

db = SessionLocal()
sc = School(name="근명고등학교", category="특성화고", region="경기", address="양주시 고암동",
           coed=Coed.coed, departments="기계과\n전기과\n소프트웨어과")
db.add(sc); db.commit(); db.refresh(sc); SID = sc.id
db.add(SchoolSubject(school_id=SID, department="소프트웨어과", grade=2, name="프로그래밍"))
db.commit()
db.close()
c = TestClient(app)
PH = {"X-Partner-Secret": "test-secret"}

print("=== 1. 인증 없이는 막힌다 ===")
chk("비밀키 없이 401", c.get(f"/api/partner/schools/{SID}/subjects").status_code == 401)
chk("틀린 비밀키 401",
    c.get(f"/api/partner/schools/{SID}/subjects", headers={"X-Partner-Secret": "wrong"}).status_code == 401)

print("=== 2. 학과·과목을 돌려준다 ===")
r = c.get(f"/api/partner/schools/{SID}/subjects", headers=PH)
chk("200", r.status_code == 200, str(r.json())[:150])
d = r.json()
chk("학과 3개(School.departments 그대로)", set(d["departments"]) == {"기계과", "전기과", "소프트웨어과"}, str(d["departments"]))
chk("과목 1개", len(d["subjects"]) == 1 and d["subjects"][0]["name"] == "프로그래밍", str(d["subjects"]))

print("=== 3. 과목 없이 학과만 있어도 정상 ===")
sc2 = School(name="이름없는고", category="특성화고", region="서울", address="종로구",
            coed=Coed.coed, departments="디자인과")
db = SessionLocal(); db.add(sc2); db.commit(); db.refresh(sc2); SID2 = sc2.id; db.close()
r = c.get(f"/api/partner/schools/{SID2}/subjects", headers=PH)
chk("과목 없어도 학과는 나옴", r.json()["departments"] == ["디자인과"], str(r.json()))
chk("과목은 빈 배열", r.json()["subjects"] == [])

print("=== 4. 없는 학교 ===")
chk("404", c.get("/api/partner/schools/999999/subjects", headers=PH).status_code == 404)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
