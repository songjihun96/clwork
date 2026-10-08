"""첫 달 무료.

확인할 것:
  (1) 기록해에 처음 들어온 학생(upsert)은 무료가 시작된다. 선생님·기존 학생은 아니다
  (2) 기간은 가입일 기준 달력 1개월: 9/27 가입 → 10/26 까지 무료. 1/31 → 2/28(윤년 2/29)
  (3) 무료 기간에는 자기소개서를 쓸 수 있고, 끝나면 402 + 상태 trial_ended
  (4) 남은 날: 7일 이하일 때만 알림(notice)
  (5) 무료 중·후 개인 이용권 결제 → paid, 유료 전환일이 잡힌다. 토스 테스트 결제는 전환으로 안 친다
  (6) 무료 정책을 끄면 새 학생에게 주지 않는다. 한 번 받은 학생은 다시 안 받는다
  (7) 관리자: 지표(신규·무료·활성·종료·전환·전환율·이용 횟수), 학생별 기간 지정·종료·빼기
실행:  cd diary-backend && python tests/free_trial.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "diary_free_trial.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ["TOSS_SECRET_KEY"] = "test_sk_x"
os.environ["TOSS_CLIENT_KEY"] = "test_ck_x"
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import date, datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main as M  # noqa: E402
from app import toss  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (CoverLetter, JournalEntry, Role, Setting,  # noqa: E402
                        SubscriptionOrder, User)

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


def prof(uid, role="student", email=None):
    return {"udj_user_id": uid, "email": email or f"u{uid}@t.kr", "name": f"학생{uid}",
            "role": role, "school_id": None, "school_name": "", "verified": False,
            "teacher_udj_id": None, "is_active": True}


print("=== 0. 달력 1개월 계산 ===")
chk("9/27 → 10/27 0시 끝(10/26 까지)", M.add_months(date(2026, 9, 27), 1) == date(2026, 10, 27))
chk("1/31 → 3/1 0시 끝(2/28 까지)", M.add_months(date(2026, 1, 31), 1) == date(2026, 3, 1))
chk("윤년 1/31 → 3/1(2/29 까지)", M.add_months(date(2028, 1, 31), 1) == date(2028, 3, 1))
chk("12/15 → 1/15", M.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15))
chk("3개월(2월 말일 다음 날)", M.add_months(date(2026, 11, 30), 3) == date(2027, 3, 1))

db = SessionLocal()
db.add_all([Setting(key="bank_name", value="국민"), Setting(key="bank_account", value="123-45"),
            Setting(key="bank_holder", value="특성화고신문")])
adm = User(udj_user_id=1, email="a@t.kr", name="관리자", role=Role.admin)
old = User(udj_user_id=2, email="old@t.kr", name="예전학생", role=Role.student)  # 정책 전 가입자
db.add_all([adm, old])
db.commit()

print("=== 1. 신규 학생은 무료 시작 ===")
new = M.upsert_user(db, prof(10))
chk("무료 시작일", new.free_trial_start_at is not None)
chk("종료 = 한국 날짜 기준 1개월 뒤 0시",
    new.free_trial_end_at == M.kst_midnight_utc(M.add_months(M.kst_date(new.free_trial_start_at), 1)),
    f"{new.free_trial_start_at} {new.free_trial_end_at}")
chk("로그인 1회", new.login_count == 1)
again = M.upsert_user(db, prof(10))
chk("다시 로그인해도 시작일 그대로", again.free_trial_start_at == new.free_trial_start_at)
chk("로그인 2회", again.login_count == 2)
tea = M.upsert_user(db, prof(11, role="teacher"))
chk("선생님은 무료 대상 아님", tea.free_trial_start_at is None)
TEA = tea.id
M.upsert_user(db, prof(2, email="old@t.kr"))
chk("기존 학생(행이 이미 있음)은 대상 아님", db.get(User, old.id).free_trial_start_at is None)

NEW = new.id
H = {u.email: {"Authorization": f"Bearer {create_access_token(u)}"} for u in (adm, new, db.get(User, old.id))}
NH, AH, OH = H["u10@t.kr"], H["a@t.kr"], H["old@t.kr"]
db.close()
c = TestClient(app)

print("=== 2. 무료 기간에는 자기소개서가 열린다 ===")
chk("자소서 200", c.get("/api/cover-letters", headers=NH).status_code == 200)
t = c.get("/api/subscription/trial-status", headers=NH).json()
chk("상태 trial", t["status"] == "trial" and t["active"] is True, str(t))
chk("남은 날 28~31", 28 <= t["days_left"] <= 31, str(t["days_left"]))
chk("아직 알림 없음(7일 초과)", t["notice"] is False)
me = c.get("/api/subscription/me", headers=NH).json()
chk("이용권 종류 trial", me["access_type"] == "trial" and me["active"] is True, str(me["access_type"]))
chk("/me 에 trial 포함", me["trial"]["status"] == "trial")
chk("예전 학생은 그대로 402", c.get("/api/cover-letters", headers=OH).status_code == 402)
chk("예전 학생 상태 none", c.get("/api/subscription/trial-status", headers=OH).json()["status"] == "none")

print("=== 3. 끝나기 7일 전부터 알림 ===")
s = SessionLocal()
u = s.get(User, NEW)
now = datetime.utcnow()
u.free_trial_end_at = M.kst_midnight_utc(M.kst_date(now) + timedelta(days=3))
s.commit()
t = c.get("/api/subscription/trial-status", headers=NH).json()
chk("3일 남음", t["days_left"] == 3, str(t["days_left"]))
chk("알림 켜짐", t["notice"] is True)
chk("마지막 무료일 = 종료 전날", t["last_day"] == (M.kst_date(now) + timedelta(days=2)).isoformat(), t["last_day"])

print("=== 4. 끝나면 막히고 유료 안내 상태 ===")
# 무료 기간에 쓴 것(통계용)
s.add(JournalEntry(user_id=NEW, kind="diary", entry_date=date.today(), title="무료 중 일지", content="{}",
                   created_at=now - timedelta(days=1)))
s.add(CoverLetter(user_id=NEW, title="무료 중 자소서", created_at=now - timedelta(days=1)))
u.free_trial_start_at = now - timedelta(days=31)
u.free_trial_end_at = now - timedelta(minutes=1)
s.commit()
s.close()
chk("자소서 402", c.get("/api/cover-letters", headers=NH).status_code == 402)
t = c.get("/api/subscription/trial-status", headers=NH).json()
chk("상태 trial_ended", t["status"] == "trial_ended" and t["active"] is False, str(t))
chk("이용권 종류 none", c.get("/api/subscription/me", headers=NH).json()["access_type"] == "none")
chk("일지는 계속 됨", c.get("/api/journals", headers=NH).status_code == 200)

print("=== 5. 유료 전환 ===")
body = {"months": 1, "method": "bank", "minor_consent": True, "guardian_contact": "010-1111-2222",
        "depositor_name": "엄마"}
o = c.post("/api/personal/orders", json=body, headers=NH).json()
chk("주문만으로는 아직 trial_ended", c.get("/api/subscription/trial-status", headers=NH).json()["status"] == "trial_ended")
r = c.post(f"/api/admin/personal-orders/{o['id']}/approve", headers=AH)
chk("입금 승인", r.status_code == 200, r.text)
t = c.get("/api/subscription/trial-status", headers=NH).json()
chk("상태 paid", t["status"] == "paid", str(t))
chk("유료 전환일", t["converted"] is True and t["converted_at"], str(t))
chk("자소서 다시 200", c.get("/api/cover-letters", headers=NH).status_code == 200)

print("=== 6. 토스 테스트 결제는 전환으로 안 친다 ===")
tu = M.upsert_user(SessionLocal(), prof(20))
TU = tu.id
TH = {"Authorization": f"Bearer {create_access_token(tu)}"}
card = {"months": 1, "method": "card", "minor_consent": True, "guardian_contact": "010-1111-2222"}
oid = c.post("/api/personal/orders", json=card, headers=TH).json()["toss"]["order_id"]
toss.confirm = lambda pk, o_, amt: (True, {"receipt": {"url": "https://r/1"}}, "")
r = c.post("/api/personal/orders/confirm", json={"payment_key": "pk", "order_id": oid, "amount": 5900},
           headers=TH)
chk("테스트 키로 승인", r.status_code == 200, r.text)
s = SessionLocal()
chk("주문에 테스트 표시", s.query(SubscriptionOrder).filter_by(order_uid=oid).first().is_test is True)
s.close()
t = c.get("/api/subscription/trial-status", headers=TH).json()
chk("이용권은 붙음(paid)", t["status"] == "paid")
chk("전환으로는 안 셈", t["converted"] is False, str(t))

print("=== 7. 정책 끄기 ===")
r = c.put("/api/admin/settings", json={"free_trial_enabled": "off"}, headers=AH)
chk("설정 저장", r.status_code == 200, r.text)
chk("설정 확인", c.get("/api/admin/settings", headers=AH).json()["free_trial_enabled"] == "off")
off = M.upsert_user(SessionLocal(), prof(30))
chk("꺼 두면 새 학생에게 안 줌", off.free_trial_start_at is None)
chk("잘못된 값 400", c.put("/api/admin/settings", json={"free_trial_months": 99}, headers=AH).status_code == 400)
c.put("/api/admin/settings", json={"free_trial_enabled": "on", "free_trial_months": 2}, headers=AH)
two = M.upsert_user(SessionLocal(), prof(31))
chk("2개월로 바꾸면 2개월",
    two.free_trial_end_at == M.kst_midnight_utc(M.add_months(M.kst_date(two.free_trial_start_at), 2)))

print("=== 8. 관리자 지표 ===")
st = c.get("/api/admin/trial/stats", headers=AH).json()
chk("학생은 못 봄", c.get("/api/admin/trial/stats", headers=NH).status_code == 403)
chk("무료 이용자 3명(10·20·31)", st["trial_users"] == 3, str(st))
chk("무료 중 2명(20·31)", st["trial_active"] == 2, str(st["trial_active"]))
chk("무료 종료 1명", st["trial_ended"] == 1, str(st["trial_ended"]))
chk("유료 전환 1명(테스트 결제 제외)", st["converted"] == 1, str(st["converted"]))
chk("전환율 33.3%", st["conversion_rate"] == 33.3, str(st["conversion_rate"]))
chk("종료자 전환율 100%", st["conversion_rate_ended"] == 100.0, str(st["conversion_rate_ended"]))
chk("무료 중 일지 1·자소서 1", st["usage"]["journals"] == 1 and st["usage"]["cover_letters"] == 1, str(st["usage"]))
chk("활성 이용자 1", st["trial_active_users"] == 1)
chk("신규 가입 학생 수(무료 없는 학생 포함)", st["new_signups"] >= 4, str(st["new_signups"]))
future = c.get("/api/admin/trial/stats", params={"start": "2099-01-01"}, headers=AH).json()
chk("기간 필터", future["trial_users"] == 0)

print("=== 9. 관리자 학생별 관리 ===")
rows = c.get("/api/admin/trial/users", headers=AH).json()
chk("목록 3명", len(rows) == 3, str(len(rows)))
chk("상태 필터", [x["id"] for x in c.get("/api/admin/trial/users", params={"status": "paid"}, headers=AH).json()]
    == [TU, NEW] or {x["id"] for x in c.get("/api/admin/trial/users", params={"status": "paid"}, headers=AH).json()} == {TU, NEW})
found = c.get("/api/admin/trial/users", params={"q": "old@"}, headers=AH).json()
chk("검색하면 무료 대상 아닌 학생도", len(found) == 1 and found[0]["status"] == "none", str(found))
OLD = found[0]["id"]
r = c.put(f"/api/admin/trial/users/{OLD}", json={"action": "set", "start_date": "2026-09-01",
                                                  "last_day": "2099-12-31"}, headers=AH)
chk("예전 학생에게 기간 지정", r.status_code == 200 and r.json()["status"] == "trial", r.text)
chk("마지막 무료일 그대로", r.json()["last_day"] == "2099-12-31", r.json()["last_day"])
chk("이제 자소서 됨", c.get("/api/cover-letters", headers=OH).status_code == 200)
r = c.put(f"/api/admin/trial/users/{OLD}", json={"action": "end"}, headers=AH)
chk("지금 종료", r.json()["status"] == "trial_ended", r.text)
chk("다시 막힘", c.get("/api/cover-letters", headers=OH).status_code == 402)
r = c.put(f"/api/admin/trial/users/{OLD}", json={"action": "clear"}, headers=AH)
chk("대상에서 빼기", r.json()["status"] == "none")
chk("거꾸로 된 기간 400", c.put(f"/api/admin/trial/users/{OLD}", json={
    "action": "set", "start_date": "2026-09-10", "last_day": "2026-09-01"}, headers=AH).status_code == 400)
chk("선생님은 대상 아님 404", c.put(f"/api/admin/trial/users/{TEA}", json={"action": "start"},
                                   headers=AH).status_code == 404)

print(f"\n{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
