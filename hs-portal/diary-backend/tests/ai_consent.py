"""AI 사용 동의 검사.

가입하면 처음부터 동의 상태다 — 자기소개서를 쓰려는 순간 벽을 한 번 더
세우지 않기 위해서다. 대신 **거둔 기록은 끝까지 존중해야 한다.** 거둔 사람이
다음에 들어올 때 다시 동의 상태로 돌아가 있으면 그건 동의가 아니라 사고다.
그 둘("기록 없음" vs "거뒀음")을 구분하는지가 이 검사의 전부다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_consent.db"
os.environ["SECRET_KEY"] = "x"
if os.path.exists("/tmp/ai_consent.db"):
    os.remove("/tmp/ai_consent.db")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
sys.path.insert(0, ".")

from fastapi.testclient import TestClient                  # noqa: E402
from app.main import app, AI_POLICY_DATE                    # noqa: E402
from app.database import SessionLocal                       # noqa: E402
from datetime import datetime, timedelta                     # noqa: E402
from datetime import date                                     # noqa: E402
from app.models import (AiConsent, JournalEntry, Role, SchoolSeat,  # noqa: E402
                        SeatHolder, User)
from app.auth import create_access_token                    # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
stu = User(udj_user_id=21, email="s@t.kr", name="홍길동", role=Role.student,
           school_id=7, school_name="근명고등학교", verified=True)
db.add(stu); db.commit(); db.refresh(stu)
# 이용권이 없으면 좌석 검사(402)가 먼저 걸려서 동의 검사까지 못 간다.
now = datetime.utcnow()
db.add(SchoolSeat(school_id=7, seats=5, started_at=now,
                  expires_at=now + timedelta(days=300)))
db.add(SeatHolder(school_id=7, user_id=stu.id))
# 없는 일지면 404 가 먼저라 동의 검사까지 못 간다.
je = JournalEntry(user_id=stu.id, kind="diary", entry_date=date(2026, 9, 1),
                  title="오늘", content="{}")
db.add(je)
db.commit(); db.refresh(je)
JID = je.id
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
SID = stu.id
db.close()

c = TestClient(app)

print("=== 1. 가입 직후 — 기록이 없다 ===")
r = c.get("/api/ai/status", headers=SH)
chk("200", r.status_code == 200, r.text[:120])
chk("처음부터 동의 상태", r.json()["consented"] is True, r.text)

print("=== 2. 거두면 거둔 채로 남는다 ===")
r = c.post("/api/ai/consent", headers=SH, json={"agreed": False})
chk("거두기 200", r.status_code == 200, r.text[:120])
chk("동의 아님", c.get("/api/ai/status", headers=SH).json()["consented"] is False)
# 다시 들어와도(새 요청) 동의 상태로 되돌아가면 안 된다
chk("다시 봐도 동의 아님",
    c.get("/api/ai/status", headers=SH).json()["consented"] is False)

print("=== 3. 거둔 사람은 AI 를 못 쓴다 ===")
r = c.post("/api/experiences/extract", headers=SH, json={"journal_id": JID})
chk("403 으로 막힌다", r.status_code == 403, str(r.status_code))

print("=== 4. 다시 동의하면 열린다 ===")
c.post("/api/ai/consent", headers=SH, json={"agreed": True})
chk("동의 상태", c.get("/api/ai/status", headers=SH).json()["consented"] is True)

print("=== 5. 방침이 바뀌면 다시 받는다 ===")
db = SessionLocal()
row = db.query(AiConsent).filter(AiConsent.user_id == SID).first()
row.policy_date = "1999-01-01"
db.commit(); db.close()
r = c.get("/api/ai/status", headers=SH)
chk("옛 동의는 인정 안 함", r.json()["consented"] is False, r.text)
chk("바뀐 것을 화면이 안다", r.json()["consent_outdated"] is True, r.text)
chk("현재 방침 날짜를 준다", r.json()["policy_date"] == AI_POLICY_DATE, r.text)

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
