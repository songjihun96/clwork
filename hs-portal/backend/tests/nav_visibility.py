# -*- coding: utf-8 -*-
"""상단 메뉴 공개 여부 검사."""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/nav.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "t"
if os.path.exists("/tmp/nav.db"):
    os.remove("/tmp/nav.db")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Role, User
from app.auth import create_access_token, hash_password

db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"), name="관리자", role=Role.admin)
stu = User(email="s@t.kr", password_hash=hash_password("p1234567"), name="학생", role=Role.student)
db.add_all([adm, stu]); db.commit(); db.refresh(adm); db.refresh(stu)
AH = {"Authorization": "Bearer " + create_access_token(adm)}
SH = {"Authorization": "Bearer " + create_access_token(stu)}
db.close()
c = TestClient(app)
OK = []
def chk(n, cond, e=""):
    OK.append(bool(cond)); print(("  OK  " if cond else "  FAIL") + "  " + n + (("  " + str(e)) if not cond and e else ""))

print("=== 상단 메뉴 공개 여부 ===")
r = c.get("/api/nav-visibility")
chk("로그인 없이 200", r.status_code == 200, r.text)
chk("설정 전에는 전부 켜짐", all(r.json().values()), r.text)
chk("관리 조회는 관리자만", c.get("/api/admin/nav-visibility").status_code in (401, 403))
chk("학생도 못 본다", c.get("/api/admin/nav-visibility", headers=SH).status_code == 403)
r = c.put("/api/admin/nav-visibility", headers=AH, json={"special": False})
chk("끄기 200", r.status_code == 200, r.text[:120])
chk("꺼졌다", c.get("/api/nav-visibility").json()["special"] is False)
chk("다른 메뉴는 그대로", c.get("/api/nav-visibility").json()["quiz"] is True)
r = c.put("/api/admin/nav-visibility", headers=AH, json={"special": True})
chk("다시 켜진다", c.get("/api/nav-visibility").json()["special"] is True)
r = c.put("/api/admin/nav-visibility", headers=AH, json={"없는키": False})
chk("모르는 키는 무시", r.status_code == 200 and "없는키" not in c.get("/api/nav-visibility").json(), r.text[:120])
chk("학생은 못 바꾼다",
    c.put("/api/admin/nav-visibility", headers=SH, json={"quiz": False}).status_code == 403)
chk("끄더라도 그 화면은 살아 있다", c.get("/api/briefing").status_code == 200)

print()
print("===== %d/%d 통과 =====" % (sum(OK), len(OK)))
sys.exit(0 if all(OK) else 1)
