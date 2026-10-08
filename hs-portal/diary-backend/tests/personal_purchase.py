"""일지 종류 필터 · 자소서 항목별 직접 고른 기록 · 개인 구매 · 학년 자동 계산.

확인할 것:
  (1) /api/journals?kind= 가 서버에서 수업일지·학교생활일지를 가른다(예전 글 포함)
  (2) 자소서의 항목별 "직접 고른 기록"이 저장된다 — 남의 일지·모르는 항목은 빠진다
  (3) 개인 구매(무통장): 주문만으로는 이용권이 없다 → 관리자 입금 확인 뒤 생긴다
  (4) 개인 구매(카드): 토스 승인이 성공해야 생긴다. 금액이 다르거나 승인이 실패하면 없다
      같은 결제를 두 번 확정해도 한 번만 붙는다
  (5) 보호자 동의 없이는 주문할 수 없다
  (6) 학교 없이(school_id 없음) 자기소개서를 쓸 수 있다. 이용권 종류가 individual 로 나온다
  (7) 환불하면 그 기간만큼 줄어든다
  (8) 개인 학생 학년: 직접 정하면 다음 학년도에 저절로 오른다(여러 번 불러도 +1 한 번),
      3학년을 넘지 않는다, UDJ 값으로 덮이지 않는다
  (9) 학교 소속 학생은 학년을 직접 못 바꾼다. 학교 코드를 넣으면 자동 계산이 멈춘다
실행:  cd diary-backend && python tests/personal_purchase.py
"""
import json
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "diary_personal_purchase.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ["TOSS_SECRET_KEY"] = "test_sk_x"
os.environ["TOSS_CLIENT_KEY"] = "test_ck_x"
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import date, datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import toss  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app, current_school_year  # noqa: E402
from app.models import (JournalEntry, Role, SchoolSeat, SeatCode, Setting,  # noqa: E402
                        Subscription, SubscriptionOrder, User)

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
adm = User(udj_user_id=1, email="a@t.kr", name="관리자", role=Role.admin)
solo = User(udj_user_id=2, email="solo@t.kr", name="혼자", role=Role.student, grade=1)
other = User(udj_user_id=3, email="o@t.kr", name="남", role=Role.student)
schooled = User(udj_user_id=4, email="sc@t.kr", name="학교생", role=Role.student,
                school_id=7, school_name="근명고", verified=True, grade=2)
tea = User(udj_user_id=5, email="t@t.kr", name="선생", role=Role.teacher, school_id=7, school_name="근명고")
db.add_all([adm, solo, other, schooled, tea])
db.commit()
db.add_all([Setting(key="bank_name", value="국민"), Setting(key="bank_account", value="123-45"),
            Setting(key="bank_holder", value="특성화고신문")])
db.add_all([
    JournalEntry(user_id=solo.id, kind="lesson", entry_date=date(2026, 5, 1), title="수업1", content="{}"),
    JournalEntry(user_id=solo.id, kind="diary", entry_date=date(2026, 5, 2), title="생활1", content="{}"),
    JournalEntry(user_id=solo.id, kind="lesson", entry_date=date(2025, 4, 1), title="예전 수업",
                 content=json.dumps({"objective": "예전 양식"}, ensure_ascii=False)),
    JournalEntry(user_id=other.id, kind="diary", entry_date=date(2026, 5, 3), title="남의 것", content="{}"),
])
now = datetime.utcnow()
db.add(SchoolSeat(school_id=7, seats=10, started_at=now, expires_at=now + timedelta(days=300)))
db.add(SeatCode(school_id=7, code="SCHL-CODE", product="essay", grade=2, class_no="1반",
                max_uses=10, created_by=tea.id, expires_at=now + timedelta(days=300)))
db.commit()
H = {u.email: {"Authorization": f"Bearer {create_access_token(u)}"} for u in (adm, solo, other, schooled)}
SOLO, OTHER = solo.id, other.id
OTHER_J = db.query(JournalEntry).filter_by(user_id=OTHER).first().id
db.close()
c = TestClient(app)
SH, AH = H["solo@t.kr"], H["a@t.kr"]

print("=== 1. 일지 종류 필터(서버) ===")
alls = c.get("/api/journals", headers=SH).json()
chk("전체 3개(남의 것 없음)", len(alls) == 3, str(len(alls)))
cls = c.get("/api/journals", params={"kind": "class"}, headers=SH).json()
chk("수업일지만", len(cls) == 2 and all(x["kind"] == "lesson" for x in cls), str(cls))
chk("예전 양식 수업일지도 수업일지로", "예전 수업" in [x["title"] for x in cls])
sch = c.get("/api/journals", params={"kind": "school"}, headers=SH).json()
chk("학교생활일지만", len(sch) == 1 and sch[0]["kind"] == "diary", str(sch))
chk("lesson/diary 이름도 받는다",
    len(c.get("/api/journals", params={"kind": "lesson"}, headers=SH).json()) == 2)
chk("all 은 전체", len(c.get("/api/journals", params={"kind": "all"}, headers=SH).json()) == 3)
chk("모르는 종류 400", c.get("/api/journals", params={"kind": "x"}, headers=SH).status_code == 400)

print("=== 2. 이용권 없으면 자소서 막힘 ===")
chk("402", c.get("/api/cover-letters", headers=SH).status_code == 402)
me = c.get("/api/subscription/me", headers=SH).json()
chk("이용권 종류 none", me["access_type"] == "none", str(me.get("access_type")))
chk("개인 구매 요금제", [p["months"] for p in me["personal"]["plans"]] == [1, 6, 12], str(me["personal"]))
chk("결제 방식", me["personal"]["pay_methods"] == {"card": True, "bank": True}, str(me["personal"]))

print("=== 3. 보호자 동의 없이 주문 불가 ===")
r = c.post("/api/personal/orders", json={"months": 1, "method": "bank"}, headers=SH)
chk("400", r.status_code == 400 and "보호자" in r.json()["detail"], r.text)
r = c.post("/api/personal/orders", json={"months": 5, "method": "bank", "minor_consent": True,
                                          "guardian_contact": "010-1111-2222"}, headers=SH)
chk("없는 기간 400", r.status_code == 400)

print("=== 4. 무통장: 입금 확인 전에는 이용권 없음 ===")
body = {"months": 1, "method": "bank", "minor_consent": True, "guardian_contact": "010-1111-2222",
        "depositor_name": "혼자엄마"}
r = c.post("/api/personal/orders", json=body, headers=SH)
chk("주문 생김", r.status_code == 200 and r.json()["status"] == "pending", r.text)
BANK = r.json()
chk("금액은 서버가 정함(5900×1)", BANK["amount"] == 5900, str(BANK["amount"]))
chk("입금 안내", BANK["bank"]["bank_account"] == "123-45" and BANK["deposit_code"].startswith("SUB-"))
chk("다시 주문하면 대기 주문을 다시 보여 줌",
    c.post("/api/personal/orders", json=body, headers=SH).json().get("reused") is True)
chk("아직 이용권 없음", c.get("/api/cover-letters", headers=SH).status_code == 402)
chk("학생은 승인 못 함",
    c.post(f"/api/admin/personal-orders/{BANK['id']}/approve", headers=SH).status_code == 403)
r = c.post(f"/api/admin/personal-orders/{BANK['id']}/approve", headers=AH)
chk("관리자 입금 확인·승인", r.status_code == 200, r.text)
chk("이제 자소서 됨(학교 없이)", c.get("/api/cover-letters", headers=SH).status_code == 200)
me = c.get("/api/subscription/me", headers=SH).json()
chk("이용권 종류 individual", me["access_type"] == "individual", str(me["access_type"]))
chk("학교 관리 아님", me["school_managed"] is False)
s = SessionLocal()
exp1 = s.query(Subscription).filter_by(user_id=SOLO).first().expires_at
chk("약 30일", 29 <= (exp1 - datetime.utcnow()).days <= 30, str(exp1))
u = s.get(User, SOLO)
chk("학년 자동 계산 시작(1학년 기준)", u.grade_base == 1 and u.grade_base_year == current_school_year(),
    f"{u.grade_base} {u.grade_base_year}")
s.close()
chk("두 번 승인 못 함",
    c.post(f"/api/admin/personal-orders/{BANK['id']}/approve", headers=AH).status_code == 400)

print("=== 5. 카드: 토스 승인 성공해야 붙는다 ===")
card = {"months": 6, "method": "card", "minor_consent": True, "guardian_contact": "010-1111-2222"}
r = c.post("/api/personal/orders", json=card, headers=SH).json()
chk("토스 정보", r["toss"]["amount"] == 5900 * 6 and r["toss"]["order_id"].startswith("DIARY-"), str(r))
OID = r["toss"]["order_id"]
calls = []
toss.confirm = lambda pk, oid, amt: (calls.append((pk, oid, amt)) or True,
                                     {"receipt": {"url": "https://r/1"}}, "")
r = c.post("/api/personal/orders/confirm", json={"payment_key": "pk1", "order_id": OID,
                                                  "amount": 100}, headers=SH)
chk("금액 조작 거절", r.status_code == 400 and not calls, r.text)
r = c.post("/api/personal/orders", json=card, headers=SH).json()
OID = r["toss"]["order_id"]
toss.confirm = lambda pk, oid, amt: (False, {}, "카드 한도 초과")
r = c.post("/api/personal/orders/confirm", json={"payment_key": "pk1", "order_id": OID,
                                                  "amount": 5900 * 6}, headers=SH)
chk("승인 실패면 거절", r.status_code == 400 and "한도" in r.json()["detail"], r.text)
s = SessionLocal()
chk("기간 그대로", s.query(Subscription).filter_by(user_id=SOLO).first().expires_at == exp1)
s.close()
r = c.post("/api/personal/orders", json=card, headers=SH).json()
OID = r["toss"]["order_id"]
toss.confirm = lambda pk, oid, amt: (calls.append((pk, oid, amt)) or True,
                                     {"receipt": {"url": "https://r/1"}}, "")
r = c.post("/api/personal/orders/confirm", json={"payment_key": "pk2", "order_id": OID,
                                                  "amount": 5900 * 6}, headers=SH)
chk("승인 성공", r.status_code == 200 and r.json()["order"]["status"] == "approved", r.text)
chk("토스에 서버 금액으로 승인 요청", calls[-1] == ("pk2", OID, 5900 * 6), str(calls))
r2 = c.post("/api/personal/orders/confirm", json={"payment_key": "pk2", "order_id": OID,
                                                   "amount": 5900 * 6}, headers=SH)
chk("두 번 확정해도 한 번만", r2.json().get("already") is True)
s = SessionLocal()
exp2 = s.query(Subscription).filter_by(user_id=SOLO).first().expires_at
chk("남은 기간 뒤에 180일 이어 붙음", 179 <= (exp2 - exp1).days <= 180, f"{exp1} → {exp2}")
s.close()
chk("남의 주문 확정 못 함", c.post("/api/personal/orders/confirm", json={
    "payment_key": "pk2", "order_id": OID, "amount": 5900 * 6}, headers=H["o@t.kr"]).status_code == 404)
lst = c.get("/api/personal/orders", headers=SH).json()
chk("내 주문 목록", len(lst) >= 4 and {"approved", "rejected"} <= {x["status"] for x in lst},
    str([x["status"] for x in lst]))

print("=== 6. 환불 ===")
approved = next(x for x in lst if x["status"] == "approved" and x["months"] == 6)
toss.cancel = lambda pk, reason, amt=None: (True, {}, "")
r = c.post(f"/api/admin/personal-orders/{approved['id']}/refund", json={"reason": "단순 변심"}, headers=AH)
chk("환불 처리", r.status_code == 200, r.text)
s = SessionLocal()
exp3 = s.query(Subscription).filter_by(user_id=SOLO).first().expires_at
chk("180일 줄어듦", abs((exp2 - exp3).days - 180) <= 1, f"{exp2} → {exp3}")
s.close()
lst = c.get("/api/personal/orders", headers=SH).json()
chk("환불 표시", any(x["status"] == "refunded" for x in lst))
chk("다시 환불 못 함", c.post(f"/api/admin/personal-orders/{approved['id']}/refund",
                             json={}, headers=AH).status_code == 400)

print("=== 7. 자소서 항목별 직접 고른 기록 ===")
mine = [x["id"] for x in alls]
r = c.post("/api/cover-letters", json={"title": "t", "content": {},
                                        "picked_records": {"teamwork": [mine[0], mine[1], OTHER_J],
                                                           "learning": [mine[2]], "없는항목": [mine[0]]}},
           headers=SH)
CL = r.json()["id"]
d = c.get(f"/api/cover-letters/{CL}", headers=SH).json()
chk("항목별로 저장", d["picked_records"] == {"teamwork": [mine[0], mine[1]], "learning": [mine[2]]},
    str(d["picked_records"]))
c.put(f"/api/cover-letters/{CL}", json={"title": "t", "content": {"teamwork": "본문"}}, headers=SH)
chk("안 보내면 그대로", c.get(f"/api/cover-letters/{CL}", headers=SH).json()["picked_records"]["learning"] == [mine[2]])
c.put(f"/api/cover-letters/{CL}", json={"title": "t", "content": {},
                                        "picked_records": {"teamwork": list(range(1, 20)) + mine}}, headers=SH)
p = c.get(f"/api/cover-letters/{CL}", headers=SH).json()["picked_records"]
chk("항목마다 5개까지, 내 것만", len(p["teamwork"]) <= 5 and set(p["teamwork"]) <= set(mine), str(p))

print("=== 8. 개인 학생 학년 자동 계산 ===")
r = c.put("/api/me/grade", json={"grade": 2}, headers=SH)
chk("직접 정함", r.status_code == 200 and r.json()["grade"] == 2 and r.json()["grade_auto"], r.text)
s = SessionLocal()
u = s.get(User, SOLO)
u.grade_base_year = current_school_year() - 1     # 기준을 작년으로 → 올해는 3학년이어야
s.commit()
s.close()
chk("다음 학년도에 저절로 +1", c.get("/api/auth/me", headers=SH).json()["grade"] == 3)
chk("여러 번 불러도 3", c.get("/api/auth/me", headers=SH).json()["grade"] == 3)
s = SessionLocal()
u = s.get(User, SOLO)
u.grade_base_year = current_school_year() - 4
s.commit()
s.close()
chk("3학년을 넘지 않음", c.get("/api/auth/me", headers=SH).json()["grade"] == 3)
s = SessionLocal()
u = s.get(User, SOLO)
u.grade_base_year = current_school_year()
u.apply_profile({"email": "solo@t.kr", "name": "혼자", "role": "student", "grade": 1})
s.commit()
chk("UDJ 학년으로 덮이지 않음", u.grade == 3 or u.grade == 2, str(u.grade))
s.close()

print("=== 9. 학교 소속 학생 ===")
r = c.put("/api/me/grade", json={"grade": 3}, headers=H["sc@t.kr"])
chk("학교 학생은 직접 못 바꿈", r.status_code == 403, r.text)
r = c.post("/api/seat-codes/redeem", json={"code": "SCHL-CODE"}, headers=SH)
chk("개인 학생이 학교 코드 등록", r.status_code == 200, r.text)
s = SessionLocal()
u = s.get(User, SOLO)
chk("자동 계산 멈춤(학교가 관리)", u.grade_base_year is None and u.grade == 2, f"{u.grade_base_year} {u.grade}")
s.close()
me = c.get("/api/subscription/me", headers=SH).json()
chk("학교+개인 둘 다", me["access_type"] == "both", me["access_type"])
chk("이제 직접 못 바꿈", c.put("/api/me/grade", json={"grade": 1}, headers=SH).status_code == 403)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
