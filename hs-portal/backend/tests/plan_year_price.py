# -*- coding: utf-8 -*-
"""플랜 연간 가격 검사.

**화면에 보인 금액과 실제 청구액이 달라지면 그건 그냥 사고다.** 그래서
계산 규칙(12개월이 찰 때마다 연 가격, 남는 달은 월 가격)을 서버 한 곳에
두고, 여기서 그 규칙만 붙잡는다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/plan_year.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "t"
if os.path.exists("/tmp/plan_year.db"):
    os.remove("/tmp/plan_year.db")
sys.path.insert(0, ".")

from fastapi.testclient import TestClient                  # noqa: E402
from app.main import app, plan_amount, get_plan_price_year  # noqa: E402
from app.database import SessionLocal                       # noqa: E402
from app.models import Plan, PlanOrder, Role, School, User   # noqa: E402
from app.auth import create_access_token, hash_password      # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
sch = School(name="근명고등학교", category="특성화고", region="경기",
             address="양주시 고암동", is_visible=True)
db.add(sch); db.commit(); db.refresh(sch)
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"),
           name="관리자", role=Role.admin)
sco = User(email="s@t.kr", password_hash=hash_password("p1234567"),
           name="학교", role=Role.school, school_id=sch.id)
db.add_all([adm, sco]); db.commit()
db.refresh(adm); db.refresh(sco)
AH = {"Authorization": "Bearer " + create_access_token(adm)}
CH = {"Authorization": "Bearer " + create_access_token(sco)}
db.close()
c = TestClient(app)

print("=== 1. 안 정하면 월 가격 × 12 ===")
db = SessionLocal()
month = 99000
c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=AH,
        params={"price": month, "per": "month"})
chk("연 가격 = 월 × 12", get_plan_price_year(db, Plan.basic) == month * 12,
    str(get_plan_price_year(db, Plan.basic)))
chk("12개월 청구도 같다", plan_amount(db, Plan.basic, 12) == month * 12)
db.close()

print("=== 2. 연 가격을 정하면 그것을 쓴다 ===")
YEAR = 800000
r = c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=AH,
            params={"price": YEAR, "per": "year"})
chk("저장 200", r.status_code == 200, r.text[:120])
chk("월 가격은 그대로", r.json()["price_per_month"] == month, r.text)
chk("연 가격이 바뀐다", r.json()["price_per_year"] == YEAR, r.text)
db = SessionLocal()
chk("12개월 = 연 가격", plan_amount(db, Plan.basic, 12) == YEAR,
    str(plan_amount(db, Plan.basic, 12)))
chk("3개월 = 월 × 3", plan_amount(db, Plan.basic, 3) == month * 3)
chk("15개월 = 연 1 + 월 3", plan_amount(db, Plan.basic, 15) == YEAR + month * 3,
    str(plan_amount(db, Plan.basic, 15)))
chk("24개월 = 연 2", plan_amount(db, Plan.basic, 24) == YEAR * 2)
chk("0개월은 0원", plan_amount(db, Plan.basic, 0) == 0)
db.close()

print("=== 3. 실제 신청 금액이 그 값이다 ===")
r = c.post("/api/school-admin/orders", headers=CH,
           json={"plan": Plan.basic.value, "months": 12, "note": ""})
chk("신청 200", r.status_code == 200, r.text[:160])
db = SessionLocal()
order = db.query(PlanOrder).order_by(PlanOrder.id.desc()).first()
chk("청구액이 연 가격", order.amount == YEAR, str(order.amount))
db.close()

print("=== 4. 화면도 같은 값을 받는다 ===")
r = c.get("/api/meta")
basic = [p for p in r.json()["plans"] if p["plan"] == Plan.basic.value][0]
chk("공개 조회에 연 가격", basic["price_per_year"] == YEAR, str(basic))
r = c.get("/api/admin/plan-prices", headers=AH)
row = [p for p in r.json() if p["plan"] == Plan.basic.value][0]
chk("관리 조회에도 있다", row["price_per_year"] == YEAR, str(row))

print("=== 5. 잘못된 입력 ===")
chk("per 가 이상하면 400",
    c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=AH,
            params={"price": 1, "per": "week"}).status_code == 400)
chk("음수는 막힌다",
    c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=AH,
            params={"price": -1, "per": "year"}).status_code == 422)
chk("학교 계정은 못 바꾼다",
    c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=CH,
            params={"price": 1, "per": "year"}).status_code == 403)
# 0 을 "1년에 0원"으로 읽으면 이 칸을 비운 순간 공짜가 된다.
c.patch(f"/api/admin/plan-prices/{Plan.basic.value}", headers=AH,
        params={"price": 0, "per": "year"})
db = SessionLocal()
chk("0 으로 비우면 월 × 12 로 돌아간다",
    get_plan_price_year(db, Plan.basic) == month * 12,
    str(get_plan_price_year(db, Plan.basic)))
db.close()

print("=== 6. 만료 현황 목록 ===")
from datetime import date, timedelta                        # noqa: E402
db = SessionLocal()
s2 = School(name="곧끝나는고", category="특성화고", region="서울",
            address="a", is_visible=True, plan=Plan.premium,
            plan_expires_at=date.today() + timedelta(days=10))
s3 = School(name="한참남은고", category="특성화고", region="부산",
            address="b", is_visible=True, plan=Plan.basic,
            plan_expires_at=date.today() + timedelta(days=200))
s4 = School(name="무료고", category="특성화고", region="대구",
            address="c", is_visible=True, plan=Plan.free)
db.add_all([s2, s3, s4]); db.commit(); db.close()

r = c.get("/api/admin/plan-expiry", headers=AH)
chk("200", r.status_code == 200, r.text[:120])
names = [x["school_name"] for x in r.json()["items"]]
chk("만료가 가까운 순서", names.index("곧끝나는고") < names.index("한참남은고"), str(names))
chk("무료 학교는 안 나온다", "무료고" not in names, str(names))
chk("남은 날을 함께 준다",
    [x for x in r.json()["items"] if x["school_name"] == "곧끝나는고"][0]["days_left"] == 10,
    r.text[:200])
chk("30일 안쪽 수를 센다", r.json()["expiring_30"] >= 1, r.text[:160])
r = c.get("/api/admin/plan-expiry", headers=AH, params={"days": 30})
names = [x["school_name"] for x in r.json()["items"]]
chk("곧 끝나는 곳만 거른다", "곧끝나는고" in names and "한참남은고" not in names, str(names))
chk("학교 계정은 못 본다",
    c.get("/api/admin/plan-expiry", headers=CH).status_code == 403)
chk("로그인 없이도 못 본다",
    c.get("/api/admin/plan-expiry").status_code in (401, 403))

print("=== 7. 끝난 학교도 남는다 ===")
from app.main import expire_plans                            # noqa: E402
db = SessionLocal()
old_s = School(name="작년에끝난고", category="특성화고", region="인천",
               address="d", is_visible=True, plan=Plan.premium,
               plan_expires_at=date.today() - timedelta(days=40))
db.add(old_s); db.commit()
expire_plans(db)
db.refresh(old_s)
chk("무료로 되돌아간다", old_s.plan == Plan.free, old_s.plan.value)
chk("끝난 날이 남는다", old_s.plan_expired_at == date.today() - timedelta(days=40),
    str(old_s.plan_expired_at))
chk("어떤 플랜이었는지도 남는다", old_s.plan_expired_from == "premium",
    str(old_s.plan_expired_from))
db.close()

r = c.get("/api/admin/plan-expiry", headers=AH)
d = r.json()
gone = [x["school_name"] for x in d["expired"]]
chk("끝난 목록에 있다", "작년에끝난고" in gone, str(gone))
one = [x for x in d["expired"] if x["school_name"] == "작년에끝난고"][0]
chk("며칠 지났는지 준다", one["days_ago"] == 40, str(one))
chk("끝나기 전 플랜 이름", one["plan_label"] == "프리미엄", str(one))
chk("돌고 있는 목록에는 없다",
    "작년에끝난고" not in [x["school_name"] for x in d["items"]], str(d["items"]))
chk("끝난 수를 센다", d["expired_count"] >= 1, str(d["expired_count"]))

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
