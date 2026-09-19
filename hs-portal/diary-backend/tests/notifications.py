"""홈 화면 알림 요약 검사.

연구를 걷어낼 때 이 엔드포인트가 같이 사라졌는데, 화면은 404 를 조용히
삼키고 있어서 아무도 못 알아챘다 — 학생 홈의 "선생님 한마디 N건 도착"이
영영 안 떴다. 다시 사라지지 않게 여기서 붙잡아 둔다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/notif.db"
os.environ["SECRET_KEY"] = "x"
if os.path.exists("/tmp/notif.db"):
    os.remove("/tmp/notif.db")
sys.path.insert(0, ".")

from datetime import date, datetime                       # noqa: E402
from fastapi.testclient import TestClient                  # noqa: E402
from app.main import app                                    # noqa: E402
from app.database import SessionLocal                       # noqa: E402
from app.models import JournalEntry, Role, User             # noqa: E402
from app.auth import create_access_token                    # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
stu = User(udj_user_id=11, email="s@t.kr", name="홍길동", role=Role.student,
           school_id=7, school_name="근명고등학교", verified=True)
other = User(udj_user_id=12, email="o@t.kr", name="다른학생", role=Role.student,
             school_id=7, school_name="근명고등학교", verified=True)
db.add_all([stu, other]); db.commit()
db.refresh(stu); db.refresh(other)
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
OH = {"Authorization": f"Bearer {create_access_token(other)}"}
SID = stu.id


def add(user_id, feedback="", read=False):
    e = JournalEntry(user_id=user_id, kind="diary", entry_date=date(2026, 9, 1),
                     title="오늘", content="{}", feedback=feedback,
                     feedback_at=datetime.utcnow() if feedback else None,
                     feedback_read_at=datetime.utcnow() if read else None)
    db.add(e); db.commit()
    return e


c = TestClient(app)

print("=== 1. 답글이 없으면 0 ===")
add(SID)                                   # 답글 없는 일지
r = c.get("/api/notifications/summary", headers=SH)
chk("200 이다(404 였다)", r.status_code == 200, r.text[:120])
chk("0건", r.json()["unread_journal_feedback"] == 0, r.text)

print("=== 2. 안 읽은 답글만 센다 ===")
add(SID, "잘했어요")                        # 안 읽음
add(SID, "이 부분 더 써보자")                # 안 읽음
add(SID, "확인했습니다", read=True)          # 읽음
r = c.get("/api/notifications/summary", headers=SH)
chk("2건", r.json()["unread_journal_feedback"] == 2, r.text)

print("=== 3. 남의 것은 안 센다 ===")
add(other.id, "다른 학생 답글")
r = c.get("/api/notifications/summary", headers=SH)
chk("여전히 2건", r.json()["unread_journal_feedback"] == 2, r.text)
r = c.get("/api/notifications/summary", headers=OH)
chk("상대는 1건", r.json()["unread_journal_feedback"] == 1, r.text)

print("=== 4. 읽으면 줄어든다 ===")
rows = db.query(JournalEntry).filter(
    JournalEntry.user_id == SID, JournalEntry.feedback != "",
    JournalEntry.feedback_read_at.is_(None)).all()
c.get(f"/api/journals/{rows[0].id}", headers=SH)     # 상세를 열면 읽음 처리된다
r = c.get("/api/notifications/summary", headers=SH)
chk("1건으로 줄었다", r.json()["unread_journal_feedback"] == 1, r.text)

print("=== 5. 로그인 안 하면 못 본다 ===")
chk("비로그인 차단", c.get("/api/notifications/summary").status_code in (401, 403))

db.close()
print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
