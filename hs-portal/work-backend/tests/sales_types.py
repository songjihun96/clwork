"""결제 유형별 매출 (우리업무).

확인할 것:
  (1) 결제 기록마다 유형이 붙는다: 기록해 개인 이용권=개인, 기록해 학교 좌석=학교,
      UDJ 플랜·구독·유료 신청=우등직, 합격생 영상=영상, 직접 입력=고른 유형(기본 기타)
  (2) 전체 매출 = 유형별 매출의 합. 건수·환불·순매출도 같다
  (3) 기간 필터(한국 날짜, 양끝 포함)와 결제 유형 필터
  (4) 토스 테스트 결제(is_test)는 매출에서 빠지고 따로 센다. is_test 칸이 없는 예전 DB 도 읽힌다
  (5) 관리자가 유형 분류를 바꾸면 그대로 따른다. 잘못된 값은 거절
  (6) 달 정산 화면에도 유형별 표(by_type)가 붙고, 합계가 정산 매출과 같다
  (7) 직원은 못 본다
  (8) 협력사는 지정된 홈페이지(방문 통계와 같은 지정)의 매출만 본다. 참고·테스트 건수는 빠진다
실행:  cd work-backend && python tests/sales_types.py
"""
import os
import sqlite3
import sys
import tempfile

T = tempfile.gettempdir()
WORK = os.path.join(T, "work_sales_types.db")
UDJ = os.path.join(T, "work_sales_udj.db")
DIARY = os.path.join(T, "work_sales_diary.db")
for p in (WORK, UDJ, DIARY):
    if os.path.exists(p):
        os.remove(p)
url = lambda p: "sqlite:///" + p.replace("\\", "/")  # noqa: E731
os.environ["DATABASE_URL"] = url(WORK)
os.environ["SALES_UDJ_DATABASE_URL"] = url(UDJ)
os.environ["SALES_DIARY_DATABASE_URL"] = url(DIARY)
os.environ["WORK_SECRET_KEY"] = "x"
sys.path.insert(0, ".")

# ── 가짜 결제 DB. 시각은 UTC 로 적는다(한국 = +9). ──
u = sqlite3.connect(UDJ)
u.executescript("""
CREATE TABLE schools (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE plan_orders (id INTEGER PRIMARY KEY, school_id INT, plan TEXT, months INT, amount INT,
  status TEXT, paid_at TIMESTAMP);
-- 예전 DB: is_test 칸이 아직 없다
CREATE TABLE subscription_orders (id INTEGER PRIMARY KEY, amount INT, months INT, paid_at TIMESTAMP,
  refunded_at TIMESTAMP);
CREATE TABLE service_applications (id INTEGER PRIMARY KEY, kind TEXT, amount INT, status TEXT,
  created_at TIMESTAMP);
INSERT INTO schools VALUES (1, '근명고');
INSERT INTO plan_orders VALUES (1, 1, 'premium', 12, 1500000, 'approved', '2026-09-10 01:00:00');
INSERT INTO plan_orders VALUES (2, 1, 'premium', 12, 999, 'pending', '2026-09-10 01:00:00');
INSERT INTO subscription_orders VALUES (1, 30000, 1, '2026-09-11 01:00:00', NULL);
INSERT INTO service_applications VALUES (1, 'graduate_video', 100000, 'paid', '2026-09-12 01:00:00');
INSERT INTO service_applications VALUES (2, 'graduate_video', 100000, 'done', '2026-09-13 01:00:00');
INSERT INTO service_applications VALUES (3, 'counseling', 100000, 'paid', '2026-09-14 01:00:00');
INSERT INTO service_applications VALUES (4, 'counseling', 100000, 'received', '2026-09-14 01:00:00');
-- 한국 날짜 10월 1일 00:30 = UTC 9월 30일 15:30. 9월 조회에 들어가면 안 된다.
INSERT INTO service_applications VALUES (5, 'graduate_video', 100000, 'paid', '2026-09-30 15:30:00');
""")
u.commit()
u.close()
d = sqlite3.connect(DIARY)
d.executescript("""
CREATE TABLE subscription_orders (id INTEGER PRIMARY KEY, amount INT, months INT, paid_at TIMESTAMP,
  refund_amount INT, refund_paid_at TIMESTAMP, is_test BOOLEAN DEFAULT 0);
CREATE TABLE seat_orders (id INTEGER PRIMARY KEY, school_name TEXT, product TEXT, seats INT,
  approved_seats INT, months INT, amount INT, status TEXT, paid_at TIMESTAMP);
INSERT INTO subscription_orders VALUES (1, 5900, 1, '2026-09-05 01:00:00', 0, NULL, 0);
INSERT INTO subscription_orders VALUES (2, 35400, 6, '2026-09-06 01:00:00', 5900, '2026-09-20 01:00:00', 0);
INSERT INTO subscription_orders VALUES (3, 5900, 1, '2026-09-07 01:00:00', 0, NULL, 1);
INSERT INTO seat_orders VALUES (1, '근명고', 'essay', 100, 100, 12, 2000000, 'approved', '2026-09-08 01:00:00');
""")
d.commit()
d.close()

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import WorkOrg, WorkUser  # noqa: E402
from app.work import make_token  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
adm = WorkUser(login_id="admin", name="관리자", password_hash="x", role="admin", must_change_password=False)
stf = WorkUser(login_id="staff", name="직원", password_hash="x", role="staff", must_change_password=False)
org_d = WorkOrg(name="기록해 협력사", visit_sites="기록해")
org_all = WorkOrg(name="전체 협력사", visit_sites=None)
org_none = WorkOrg(name="안 보이는 협력사", visit_sites="")
db.add_all([adm, stf, org_d, org_all, org_none])
db.commit()
pd = WorkUser(login_id="pd", name="협력D", password_hash="x", role="partner", org_id=org_d.id, must_change_password=False)
pa = WorkUser(login_id="pa", name="협력A", password_hash="x", role="partner", org_id=org_all.id, must_change_password=False)
pn = WorkUser(login_id="pn", name="협력N", password_hash="x", role="partner", org_id=org_none.id, must_change_password=False)
db.add_all([pd, pa, pn])
db.commit()
PDH, PAH, PNH = ({"Authorization": f"Bearer {make_token(u)}"} for u in (pd, pa, pn))
AH = {"Authorization": f"Bearer {make_token(adm)}"}
SH = {"Authorization": f"Bearer {make_token(stf)}"}
db.close()
c = TestClient(app)

print("=== 0. 직접 입력(결제 유형 선택) ===")
r = c.post("/api/work/settlement/entries", headers=AH, json={
    "month": "2026-09", "kind": "sale", "site": "기타", "amount": 500000, "memo": "계좌이체 계약",
    "day": "2026-09-15", "payment_type": "school"})
chk("학교 결제로 직접 입력", r.status_code == 200, r.text)
r = c.post("/api/work/settlement/entries", headers=AH, json={
    "month": "2026-09", "kind": "sale", "site": "기타", "amount": 70000, "memo": "날짜 없음"})
chk("유형 안 고르면 기타", r.status_code == 200)
chk("모르는 유형 400", c.post("/api/work/settlement/entries", headers=AH, json={
    "month": "2026-09", "amount": 1, "payment_type": "zzz"}).status_code == 400)

print("=== 1. 9월 전체 ===")
r = c.get("/api/work/sales", params={"start": "2026-09-01", "end": "2026-09-30"}, headers=AH)
chk("200", r.status_code == 200, r.text)
s = r.json()
chk("경고 없음", s["warnings"] == [], str(s["warnings"]))
T_ = {t["key"]: t for t in s["types"]}
chk("유형 다섯 개, 순서 고정", [t["key"] for t in s["types"]] == ["personal", "school", "udj", "video", "other"])
chk("개인 = 기록해 개인 이용권 2건(테스트 제외)", T_["personal"]["count"] == 2 and T_["personal"]["sales"] == 5900 + 35400,
    str(T_["personal"]))
chk("개인 환불 5900", T_["personal"]["refunds"] == 5900)
chk("학교 = 좌석 + 직접 입력", T_["school"]["count"] == 2 and T_["school"]["sales"] == 2_500_000, str(T_["school"]))
chk("우등직 = 플랜 + 구독 + 상담", T_["udj"]["count"] == 3 and T_["udj"]["sales"] == 1_500_000 + 30000 + 100000,
    str(T_["udj"]))
chk("영상 = 합격생 영상 2건(10월 1일 한국 날짜 건 제외)", T_["video"]["count"] == 2 and T_["video"]["sales"] == 200000,
    str(T_["video"]))
chk("기타 = 날짜 없는 직접 입력(그 달 1일)", T_["other"]["sales"] == 70000, str(T_["other"]))
chk("전체 = 유형 합", s["total"]["sales"] == sum(t["sales"] for t in s["types"]) == 4_441_300, str(s["total"]))
chk("건수 합", s["total"]["count"] == sum(t["count"] for t in s["types"]) == 10, str(s["total"]))
chk("순매출", s["total"]["net"] == s["total"]["sales"] - s["total"]["refunds"])
chk("비율 합 ≈ 100", abs(sum(t["ratio"] for t in s["types"]) - 100) < 0.5, str([t["ratio"] for t in s["types"]]))
chk("테스트 결제 따로 1건 5,900", s["test"] == {"count": 1, "sales": 5900, "refunds": 0}, str(s["test"]))
chk("명세 줄에 유형", all(x["payment_type"] in T_ for x in s["lines"]))
chk("예전 DB(is_test 칸 없음)도 읽힘", any(x.get("source_key") == "udj_sub" for x in s["lines"]))

print("=== 2. 필터 ===")
v = c.get("/api/work/sales", params={"start": "2026-09-01", "end": "2026-09-30", "payment_type": "video"},
          headers=AH).json()
chk("영상만 명세", len(v["lines"]) == 2 and all(x["payment_type"] == "video" for x in v["lines"]))
chk("유형 필터를 걸어도 요약표는 전체", v["total"]["sales"] == 4_441_300)
chk("선택 유형 요약", v["selected"]["key"] == "video" and v["selected"]["sales"] == 200000)
o = c.get("/api/work/sales", params={"start": "2026-10-01", "end": "2026-10-01"}, headers=AH).json()
chk("10월 1일(한국) = 합격생 영상 1건", o["total"]["sales"] == 100000 and o["types"][3]["count"] == 1, str(o["total"]))
w = c.get("/api/work/sales", params={"start": "2026-09-10", "end": "2026-09-10"}, headers=AH).json()
chk("하루만(플랜)", w["total"]["sales"] == 1_500_000, str(w["total"]))
chk("거꾸로 된 기간 400", c.get("/api/work/sales", params={"start": "2026-09-30", "end": "2026-09-01"},
                               headers=AH).status_code == 400)
chk("모르는 유형 400", c.get("/api/work/sales", params={"payment_type": "x"}, headers=AH).status_code == 400)
chk("너무 긴 기간 400", c.get("/api/work/sales", params={"start": "2024-01-01", "end": "2026-09-30"},
                             headers=AH).status_code == 400)
chk("직원은 403", c.get("/api/work/sales", headers=SH).status_code == 403)

print("=== 3. 달 정산과 맞는가 ===")
m = c.get("/api/work/settlement", params={"month": "2026-09"}, headers=AH).json()
chk("정산 매출 = 기간 매출", m["sales"] == s["total"]["sales"], f"{m['sales']} vs {s['total']['sales']}")
chk("정산 환불 = 기간 환불", m["refunds"] == s["total"]["refunds"])
chk("정산에 유형별 표", m["by_type"] and sum(t["sales"] for t in m["by_type"]) == m["sales"])

print("=== 4. 유형 분류 바꾸기 ===")
st = c.get("/api/work/settlement/settings", headers=AH).json()
chk("출처 목록", {x["key"] for x in st["sources"]} >= {"udj_plan", "udj_video", "diary_sub", "diary_seat"})
chk("기본 분류", st["ptype_map"]["udj_plan"] == "udj" and st["ptype_map"]["udj_video"] == "video")
r = c.put("/api/work/settlement/settings", headers=AH, json={"ptype_map": {"udj_plan": "school"}})
chk("UDJ 학교 플랜을 학교 결제로", r.status_code == 200 and r.json()["ptype_map"]["udj_plan"] == "school", r.text)
s2 = c.get("/api/work/sales", params={"start": "2026-09-01", "end": "2026-09-30"}, headers=AH).json()
T2 = {t["key"]: t for t in s2["types"]}
chk("학교 결제로 옮겨짐", T2["school"]["sales"] == 4_000_000 and T2["udj"]["sales"] == 130000, str(T2["school"]))
chk("전체는 그대로", s2["total"]["sales"] == 4_441_300)
chk("잘못된 분류 400", c.put("/api/work/settlement/settings", headers=AH,
                            json={"ptype_map": {"udj_plan": "zzz"}}).status_code == 400)
chk("모르는 출처 400", c.put("/api/work/settlement/settings", headers=AH,
                            json={"ptype_map": {"nope": "udj"}}).status_code == 400)
chk("직원은 분류 못 바꿈", c.put("/api/work/settlement/settings", headers=SH,
                               json={"ptype_map": {"udj_plan": "udj"}}).status_code == 403)
c.put("/api/work/settlement/settings", headers=AH, json={"ptype_map": {"udj_plan": "udj"}})

print("=== 5. 협력사: 지정된 홈페이지만 ===")
Q = {"start": "2026-09-01", "end": "2026-09-30"}
r = c.get("/api/work/sales", params=Q, headers=PDH)
chk("기록해 지정 협력사 200", r.status_code == 200, r.text)
p = r.json()
chk("사이트 표시", p["sites"] == ["기록해"])
chk("기록해 줄만", p["lines"] and all(x["site"] == "기록해" for x in p["lines"]), str({x["site"] for x in p["lines"]}))
chk("기록해 매출만 합계(개인 41,300 + 좌석 2,000,000)", p["total"]["sales"] == 2_041_300, str(p["total"]))
chk("유형 합 = 전체", sum(t["sales"] for t in p["types"]) == p["total"]["sales"])
chk("참고(주문 번호·학교명) 없음", all("ref" not in x for x in p["lines"]))
chk("테스트 건수 안 보임", p["test"]["count"] == 0)
pa_ = c.get("/api/work/sales", params=Q, headers=PAH).json()
chk("전체 지정 협력사는 두 사이트", set(pa_["sites"]) == {"우리동네 직업계고", "기록해"})
chk("직접 입력(기타 사이트)은 협력사에게 안 보임", pa_["total"]["sales"] == 4_441_300 - 570_000, str(pa_["total"]))
chk("지정 사이트 없는 협력사 403", c.get("/api/work/sales", params=Q, headers=PNH).status_code == 403)
chk("직원은 여전히 403", c.get("/api/work/sales", params=Q, headers=SH).status_code == 403)

print(f"\n{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
