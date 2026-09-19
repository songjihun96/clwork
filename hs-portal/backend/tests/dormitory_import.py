"""학교알리미 기숙사실수 자동 채우기(import_dormitory) 검사.

실제 API는 부르지 않고 requests.get을 흉내 낸다 — 여기서 보는 것은
"이름으로 잘 이어붙이는가·기존 값을 지키는가·제외 학교를 건드리지 않는가"다.
"""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/dorm.db"; os.environ["SECRET_KEY"] = "x"
if os.path.exists("/tmp/dorm.db"):
    os.remove("/tmp/dorm.db")
os.environ["SCHOOLINFO_API_KEY"] = "test-key"
sys.path.insert(0, ".")

import requests
from app.database import Base, SessionLocal, engine
from app.models import Coed, School
from app import import_dormitory

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

Base.metadata.create_all(bind=engine)

db = SessionLocal()
s_has = School(name="양주기계고등학교", category="특성화고", region="경기",
              address="a", coed=Coed.coed, is_visible=True, dormitory=None)
s_no = School(name="서울소프트웨어고등학교", category="특성화고", region="서울",
             address="a", coed=Coed.coed, is_visible=True, dormitory=None)
s_already_set = School(name="이미확인고등학교", category="특성화고", region="경기",
                       address="a", coed=Coed.coed, is_visible=True, dormitory=False)
s_excluded = School(name="공시제외고등학교", category="특성화고", region="경기",
                    address="a", coed=Coed.coed, is_visible=True, dormitory=None)
s_unmatched = School(name="자료에없는고등학교", category="특성화고", region="경기",
                     address="a", coed=Coed.coed, is_visible=True, dormitory=None)
for s in (s_has, s_no, s_already_set, s_excluded, s_unmatched):
    db.add(s)
db.commit()
[db.refresh(s) for s in (s_has, s_no, s_already_set, s_excluded, s_unmatched)]
db.close()


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = str(payload)
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


FAKE_LIST = [
    {"SCHUL_NM": "양주기계고등학교", "ATPT_OFCDC_ORG_NM": "경기도교육청",
     "COL_13": "3", "PBAN_EXCP_YN": "N"},
    {"SCHUL_NM": "서울소프트웨어고등학교", "ATPT_OFCDC_ORG_NM": "서울특별시교육청",
     "COL_13": "0", "PBAN_EXCP_YN": "N"},
    {"SCHUL_NM": "이미확인고등학교", "ATPT_OFCDC_ORG_NM": "경기도교육청",
     "COL_13": "5", "PBAN_EXCP_YN": "N"},
    {"SCHUL_NM": "공시제외고등학교", "ATPT_OFCDC_ORG_NM": "경기도교육청",
     "COL_13": "", "PBAN_EXCP_YN": "Y"},
]


def fake_get(url, params=None, timeout=None):
    assert params["apiType"] == "17"
    assert params["schulKndCode"] == "04"
    return FakeResponse({"resultCode": "success", "resultMsg": "성공", "list": FAKE_LIST})


requests.get = fake_get
import_dormitory.time.sleep = lambda *_: None  # 256개 지역을 도는 실제 대기는 검사에선 필요 없다

print("=== 1. 기본 실행 — 미확인 학교만 채운다 ===")
sys.argv = ["import_dormitory.py", "--year", "2026"]
code = import_dormitory.main()
chk("정상 종료", code == 0, str(code))

db = SessionLocal()
r_has = db.get(School, s_has.id)
r_no = db.get(School, s_no.id)
r_already_set = db.get(School, s_already_set.id)
r_excluded = db.get(School, s_excluded.id)
r_unmatched = db.get(School, s_unmatched.id)
chk("기숙사실수 3 -> True", r_has.dormitory is True, str(r_has.dormitory))
chk("기숙사실수 0 -> False", r_no.dormitory is False, str(r_no.dormitory))
chk("이미 값 있던 학교는 안 건드림(False 유지, 자료는 5실)", r_already_set.dormitory is False, str(r_already_set.dormitory))
chk("공시 제외 학교는 안 건드림(여전히 None)", r_excluded.dormitory is None, str(r_excluded.dormitory))
chk("자료에 없는 학교는 안 건드림(여전히 None)", r_unmatched.dormitory is None, str(r_unmatched.dormitory))
db.close()

print("=== 2. --force — 이미 값 있어도 덮어쓴다 ===")
sys.argv = ["import_dormitory.py", "--year", "2026", "--force"]
import_dormitory.main()
db = SessionLocal()
r_already_set2 = db.get(School, s_already_set.id)
chk("--force로 False -> True(기숙사실수 5)", r_already_set2.dormitory is True, str(r_already_set2.dormitory))
db.close()

print("=== 3. --dry-run — 저장하지 않는다 ===")
# 새 학교를 하나 더 만들어(미확인) dry-run으로 실제 반영 안 되는지 본다
db = SessionLocal()
s_dry = School(name="드라이런고등학교", category="특성화고", region="경기",
              address="a", coed=Coed.coed, is_visible=True, dormitory=None)
db.add(s_dry); db.commit(); db.refresh(s_dry); dry_id = s_dry.id
db.close()

FAKE_LIST.append({"SCHUL_NM": "드라이런고등학교", "ATPT_OFCDC_ORG_NM": "경기도교육청",
                  "COL_13": "2", "PBAN_EXCP_YN": "N"})
sys.argv = ["import_dormitory.py", "--year", "2026", "--dry-run"]
import_dormitory.main()
db = SessionLocal()
after = db.get(School, dry_id)
chk("dry-run은 실제로 저장 안 함(여전히 None)", after.dormitory is None, str(after.dormitory))
db.close()

print("\n" + ("=" * 5) + f" {sum(OK)}/{len(OK)} 통과 " + ("=" * 5))
if not all(OK):
    sys.exit(1)
