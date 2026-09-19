"""학과·과목 드롭다운을 UDJ 에서 실시간으로 받아오는지 확인한다.

전에는 로컬에 한 번 옮겨온 사본만 썼는데, 그 사본이 비어 있거나 낡으면
학과가 하나도 안 보이는 문제가 있었다. 이제는 UDJ 를 먼저 불러보고,
안 되면(연동 미설정 포함) 로컬 사본으로 조용히 물러난다.
"""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/js.db"; os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-secret"
os.environ["UDJ_API_BASE"] = "http://udj.test"

if os.path.exists("/tmp/js.db"):
    os.remove("/tmp/js.db")
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

db = SessionLocal()
SCHOOL = 77
tea = User(udj_user_id=501, email="t@t.kr", name="교사", role=Role.teacher, school_id=SCHOOL)
db.add(tea); db.commit(); db.refresh(tea)
TH = {"Authorization": f"Bearer {create_access_token(tea)}"}
db.close()
c = TestClient(app)


class Res:
    def __init__(self, code, body):
        self.status_code = code; self._b = body
    def json(self): return self._b

print("=== 1. 로컬 사본이 비어 있어도 UDJ 응답으로 채워진다 ===")
def fake_request(method, url, headers=None, timeout=None, **kw):
    assert url.endswith(f"/api/partner/schools/{SCHOOL}/subjects")
    return Res(200, {"school_name": "근명고", "departments": ["소프트웨어과", "전기과"],
                     "subjects": [{"department": "소프트웨어과", "grade": 2, "name": "프로그래밍"}]})
requests.request = fake_request

r = c.get("/api/journal-subjects", headers=TH)
chk("200", r.status_code == 200)
d = r.json()
chk("UDJ 학과가 그대로 나옴", set(d["departments"]) == {"소프트웨어과", "전기과"}, str(d["departments"]))
chk("과목도 로컬에 캐시됨",
    len(db_check_subjects := SessionLocal().query(SchoolSubject)
        .filter(SchoolSubject.school_id == SCHOOL).all()) == 1,
    str([s.name for s in db_check_subjects]))

print("=== 2. UDJ 가 안 되면 로컬 캐시로 물러난다 ===")
def fail_request(method, url, headers=None, timeout=None, **kw):
    raise requests.RequestException("연결 안 됨")
requests.request = fail_request

r = c.get("/api/journal-subjects", headers=TH)
chk("200 (터지지 않음)", r.status_code == 200, str(r.status_code))
d = r.json()
chk("직전에 캐시해 둔 학과가 남아 있음", "소프트웨어과" in d["departments"], str(d["departments"]))
chk("직전에 캐시해 둔 과목이 남아 있음", "프로그래밍" in d["subjects"], str(d["subjects"]))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
