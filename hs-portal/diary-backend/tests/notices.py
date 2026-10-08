"""기록해 공지사항(UDJ 공지와 별개) · 학교 계정 공지 알림 메일.

확인할 것:
  (1) 작성·임시저장·게시·게시 취소·수정·삭제, 중요 공지가 위, 비로그인도 목록·상세
  (2) 메일은 학교 계정에만(학생·선생님 X), 학교급 대상, 알림 끈 학교 제외, 공지 알림 이메일 우선
  (3) 다시 게시해도 중복 발송 없음, 실패 기록·재발송, 주소 가림
  (4) 학교 계정 공지 알림 설정, 학교급은 UDJ 프로필에서(학생 school_level 은 안 건드림)
실행:  cd diary-backend && python tests/notices.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "diary_notices_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app import mailer, notices as N  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


SENT = []
FAIL_TO = set()


def fake_send(to, subject, body, from_name="기록해"):
    if to in FAIL_TO:
        return False, "SMTP 오류"
    SENT.append((to, subject, body))
    return True, ""


mailer.send = fake_send

db = SessionLocal()
adm = User(udj_user_id=1, email="a@t.kr", name="관리자", role=Role.admin)
hs = User(udj_user_id=2, email="hs@school.kr", name="고교", role=Role.school, school_id=10,
          school_name="한빛공고", school_level="high")
ms = User(udj_user_id=3, email="ms@school.kr", name="중학", role=Role.school, school_id=20,
          school_name="푸른중", school_level="middle")
off = User(udj_user_id=4, email="off@school.kr", name="정지", role=Role.school, school_id=30,
           school_name="정지고", is_active=False)
stu = User(udj_user_id=5, email="stu@t.kr", name="학생", role=Role.student, school_id=10)
tea = User(udj_user_id=6, email="tea@t.kr", name="선생", role=Role.teacher, school_id=10)
db.add_all([adm, hs, ms, off, stu, tea])
db.commit()
H = {u.email: {"Authorization": f"Bearer {create_access_token(u)}"} for u in (adm, hs, ms, stu)}
AH, HH, MH, SH = H["a@t.kr"], H["hs@school.kr"], H["ms@school.kr"], H["stu@t.kr"]
db.close()
c = TestClient(app)

print("=== 1. 공지 ===")
r = c.post("/api/admin/notices", headers=AH, json={"title": "초안", "publish": False})
DRAFT = r.json()["id"]
chk("임시저장", r.json()["status"] == "draft")
chk("임시저장은 안 보임", c.get(f"/api/notices/{DRAFT}").status_code == 404
    and c.get("/api/notices").json()["total"] == 0)
chk("관리자는 임시저장 상세를 봄", c.get(f"/api/notices/{DRAFT}", headers=AH).status_code == 200)
A = c.post("/api/admin/notices", headers=AH, json={"title": "업데이트 안내", "category": "update"}).json()["id"]
B = c.post("/api/admin/notices", headers=AH, json={"title": "점검", "is_important": True,
                                                    "category": "maintenance"}).json()["id"]
items = c.get("/api/notices").json()["items"]
chk("비로그인 목록, 중요 공지가 위", [i["id"] for i in items] == [B, A], str(items))
chk("유형 필터", [i["id"] for i in c.get("/api/notices", params={"category": "update"}).json()["items"]] == [A])
chk("상세", c.get(f"/api/notices/{A}").json()["title"] == "업데이트 안내")
chk("수정", c.put(f"/api/admin/notices/{A}", headers=AH, json={"title": "고친 제목", "category": "update"})
    .json()["title"] == "고친 제목")
chk("게시 취소", c.post(f"/api/admin/notices/{A}/unpublish", headers=AH).json()["status"] == "draft"
    and c.get(f"/api/notices/{A}").status_code == 404)
chk("학생은 관리 403", c.post("/api/admin/notices", headers=SH, json={"title": "x"}).status_code == 403)
chk("삭제", c.delete(f"/api/admin/notices/{DRAFT}", headers=AH).status_code == 200)

print("=== 2. 학교 계정 메일 ===")
pv = c.post("/api/admin/notices/preview", headers=AH, json={"title": "t", "email_enabled": True}).json()
chk("미리보기: 활성 학교 2, 정지 1", pv["email"] == 2 and pv["inactive"] == 1, str(pv))
SENT.clear()
r = c.post("/api/admin/notices", headers=AH, json={"title": "전체 학교", "body": "본문", "email_enabled": True})
ALLN = r.json()["id"]
N.process()
chk("학교 계정 2곳에만", sorted(x[0] for x in SENT) == ["hs@school.kr", "ms@school.kr"], str(SENT))
chk("학생·선생님에게 안 감", not any(x[0] in ("stu@t.kr", "tea@t.kr") for x in SENT))
chk("제목 머리", SENT[0][1].startswith("[기록해] "))
SENT.clear()
c.post("/api/admin/notices", headers=AH, json={"title": "중학교만", "email_enabled": True,
                                                "target_level": "middle"})
N.process()
chk("중학교 대상 → 중학교만", [x[0] for x in SENT] == ["ms@school.kr"], str(SENT))

print("=== 4. 알림 설정 ===")
chk("학생은 설정 403", c.get("/api/school/notification-settings", headers=SH).status_code == 403)
r = c.put("/api/school/notification-settings", headers=HH, json={"notice_email": "notice@hs.kr",
                                                                  "enabled": True})
chk("공지 알림 이메일 저장", r.json()["notice_email"] == "notice@hs.kr")
chk("잘못된 메일 422", c.put("/api/school/notification-settings", headers=HH,
                            json={"notice_email": "bad"}).status_code == 422)
c.put("/api/school/notification-settings", headers=MH, json={"notice_email": "", "enabled": False})
SENT.clear()
c.post("/api/admin/notices", headers=AH, json={"title": "설정 확인", "email_enabled": True})
N.process()
chk("공지 알림 이메일로, 알림 끈 학교 제외", [x[0] for x in SENT] == ["notice@hs.kr"], str(SENT))

print("=== 3. 중복 방지·재발송 ===")
SENT.clear()
c.post(f"/api/admin/notices/{ALLN}/unpublish", headers=AH)
c.post(f"/api/admin/notices/{ALLN}/publish", headers=AH)
N.process()
chk("다시 게시해도 안 감", SENT == [], str(SENT))
FAIL_TO.add("notice@hs.kr")
r = c.post("/api/admin/notices", headers=AH, json={"title": "실패 시험", "email_enabled": True})
FN = r.json()["id"]
N.process()
logs = c.get(f"/api/admin/notices/{FN}/logs", headers=AH).json()
chk("실패 기록", [x["status"] for x in logs] == ["failed"] and "SMTP" in logs[0]["error"], str(logs))
chk("주소 가림", "***" in logs[0]["address"])
FAIL_TO.clear()
SENT.clear()
c.post(f"/api/admin/notification-logs/{logs[0]['id']}/retry", headers=AH)
N.process()
chk("재발송 성공", [x[0] for x in SENT] == ["notice@hs.kr"], str(SENT))
chk("보낸 건 재발송 거부", c.post(f"/api/admin/notification-logs/{logs[0]['id']}/retry",
                                headers=AH).status_code == 409)
lst = c.get("/api/admin/notices", headers=AH).json()
chk("목록 발송 집계", next(x for x in lst if x["id"] == FN)["send"]["email"]["sent"] == 1)

print("=== 이벤트는 메일 안 보냄 ===")
SENT.clear()
r = c.post("/api/admin/notices", headers=AH, json={"title": "가을 이벤트", "category": "event",
                                                    "email_enabled": True})
chk("이벤트: 메일 꺼짐", r.json()["email_enabled"] is False, r.text)
N.process()
chk("이벤트: 안 감", SENT == [], str(SENT))
pv = c.post("/api/admin/notices/preview", headers=AH, json={"title": "t", "category": "event",
                                                             "email_enabled": True}).json()
chk("이벤트 미리보기 0건", pv["email"] == 0, str(pv))

print("=== 학교급은 UDJ 프로필에서 ===")
db = SessionLocal()
u = db.query(User).filter_by(email="hs@school.kr").first()
u.apply_profile({"email": u.email, "name": u.name, "role": "school", "school_id": 10,
                 "school_name": "한빛공고", "school_level": "middle", "is_active": True})
s = db.query(User).filter_by(email="stu@t.kr").first()
before = s.school_level
s.apply_profile({"email": s.email, "name": s.name, "role": "student", "school_id": 10,
                 "school_level": "middle", "is_active": True})
chk("학교 계정 학교급 갱신", u.school_level == "middle")
chk("학생 school_level 은 그대로", s.school_level == before)
db.rollback()
db.close()

print(f"\n{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
