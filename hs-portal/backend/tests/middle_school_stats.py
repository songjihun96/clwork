"""관리자 통계 · 가입 중학교 지역별 현황(영업용).

확인할 것:
  (1) /api/admin/stats 의 middle_school_stats: 지역별 가입 중학교 수, 17개 시·도 모두(0 포함),
      정지 계정만 있는 학교·계정 없는 학교는 빼고, 최근 30일 신규·신청 대기(처리 중)를 센다
  (2) 승인 API 로 가입한 중학교가 그 지역에 잡힌다
  (3) 직업계고 숫자(학교 수·지역별·플랜)에 중학교가 섞이지 않는다
  (4) CSV 리포트에 [11. 중학교 가입 현황 — 지역별] 표가 들어가고, [2] 계정 개설에 중학교가 안 섞인다
실행:  cd backend && python tests/middle_school_stats.py
"""
import csv
import io
import os
import sys
import tempfile
from datetime import datetime, timedelta

DB = os.path.join(tempfile.gettempdir(), "udj_middle_stats_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app import mailer  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Coed, Plan, Role, School, SchoolAccountRequest, User  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


mailer.send_email = lambda *a, **k: (True, "")

db = SessionLocal()


def mk_school(name, region, level="high"):
    s = School(name=name, category="특성화고" if level == "high" else "중학교", region=region,
               address="", coed=Coed.coed, plan=Plan.free, is_visible=(level == "high"),
               phone="", school_level=level)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def mk_user(email, role, school_id=None, active=True, created=None):
    u = User(email=email, password_hash=hash_password("p1234567"), name=email, role=role,
             school_id=school_id, is_active=active)
    if created:
        u.created_at = created
    db.add(u)
    db.commit()
    return u


OLD = datetime.utcnow() - timedelta(days=90)
H1 = mk_school("한빛공업고", "경기")
H2 = mk_school("부산공고", "부산")
M1 = mk_school("푸른중", "경기", "middle")      # 가입(오래전)
M2 = mk_school("하늘중", "경기", "middle")      # 가입(최근), 계정 2개
M3 = mk_school("바다중", "부산", "middle")      # 가입(최근)
M4 = mk_school("정지중", "서울", "middle")      # 정지 계정만 → 가입 아님
M5 = mk_school("계정없는중", "대구", "middle")  # 계정 없음 → 가입 아님
adm = mk_user("admin@t.kr", Role.admin)
mk_user("h1@school.kr", Role.school, H1.id)
mk_user("m1@school.kr", Role.school, M1.id, created=OLD)
mk_user("m2a@school.kr", Role.school, M2.id)
mk_user("m2b@school.kr", Role.school, M2.id)
mk_user("m3@school.kr", Role.school, M3.id)
mk_user("m4@school.kr", Role.school, M4.id, active=False)
mk_user("stu@t.kr", Role.student, M1.id)        # 학생은 학교 계정이 아니다


def req(name, level, region, status):
    db.add(SchoolAccountRequest(school_name=name, school_level=level, region=region,
                                manager_name="담당", manager_phone="010-1234-5678",
                                manager_email=f"{name}@req.kr", status=status))
    db.commit()


req("대기중", "middle", "광주", "received")
req("통화중", "middle", "광주", "called")
req("반려중", "middle", "광주", "rejected")    # 처리 끝 → 대기 아님
req("고교대기", "high", "광주", "received")    # 고등학교 → 중학교 대기 아님
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
db.close()
c = TestClient(app)


def region(ms, r):
    return next((x for x in ms["by_region"] if x["region"] == r), None)


print("=== 1. 관리자 통계 ===")
st = c.get("/api/admin/stats", headers=AH).json()
ms = st["middle_school_stats"]
chk("전체 가입 중학교 3", ms["total"] == 3, ms)
chk("경기 2(계정 2개여도 학교 1개로)", region(ms, "경기")["joined"] == 2)
chk("부산 1", region(ms, "부산")["joined"] == 1)
chk("정지 계정만 있는 서울 0", region(ms, "서울")["joined"] == 0)
chk("계정 없는 대구 0", region(ms, "대구")["joined"] == 0)
chk("17개 시·도 모두 나옴", len(ms["by_region"]) == 17
    and [x["region"] for x in ms["by_region"]][:2] == ["서울", "부산"])
chk("최근 30일 신규 2(경기 1·부산 1)", ms["recent30"] == 2
    and region(ms, "경기")["recent30"] == 1 and region(ms, "부산")["recent30"] == 1)
chk("신청 대기 2(광주, 처리 중인 중학교만)", ms["pending"] == 2 and region(ms, "광주")["pending"] == 2)

print("=== 2. 승인하면 그 지역에 잡힘 ===")
db = SessionLocal()
r = SchoolAccountRequest(school_name="새중", school_level="middle", region="제주",
                         manager_name="담당", manager_phone="010-2222-3333",
                         manager_email="new@mid.kr", status="called")
db.add(r)
db.commit()
RID = r.id
db.close()
res = c.post(f"/api/admin/school-account-requests/{RID}/approve", headers=AH)
chk("승인", res.status_code == 200, res.text[:200])
ms = c.get("/api/admin/stats", headers=AH).json()["middle_school_stats"]
chk("제주 1, 전체 4, 최근 30일 3", region(ms, "제주")["joined"] == 1 and ms["total"] == 4
    and ms["recent30"] == 3, ms)

print("=== 3. 직업계고 숫자에 중학교 안 섞임 ===")
st = c.get("/api/admin/stats", headers=AH).json()
chk("학교 수 = 고등학교 2", st["school_count"] == 2, st["school_count"])
chk("지역별 학교 수에 중학교 없음", st["region_distribution"] == {"경기": 1, "부산": 1}
    or st["region_distribution"] == {"부산": 1, "경기": 1}, st["region_distribution"])
chk("플랜 분포 합 = 2", sum(st["plan_distribution"].values()) == 2)

print("=== 4. CSV 리포트 ===")
res = c.get("/api/admin/stats/export", headers=AH)
chk("내려받기", res.status_code == 200)
rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))
i = next((k for k, row in enumerate(rows) if row and row[0].startswith("[11. 중학교 가입 현황")), None)
chk("[11] 표 있음", i is not None)
if i is not None:
    head = rows[i + 1]
    body = {row[0]: row for row in rows[i + 2:i + 2 + 19] if row}
    chk("머리글", head[:4] == ["지역", "가입 중학교 수", "최근 30일 신규", "신청 대기"], head)
    chk("경기 2·최근 1", body.get("경기", [])[1:3] == ["2", "1"], body.get("경기"))
    chk("광주 대기 2", body.get("광주", [])[3:4] == ["2"], body.get("광주"))
    chk("합계 4", body.get("합계", [])[1:2] == ["4"], body.get("합계"))
k = next(k for k, row in enumerate(rows) if row and row[0] == "학교 계정 개설")
chk("[2] 계정 개설 = 고등학교 1(중학교 안 섞임)", rows[k][1] == "1", rows[k])
k = next(k for k, row in enumerate(rows) if row and row[0] == "등록 학교 수")
chk("[1] 등록 학교 수 = 2", rows[k][1] == "2", rows[k])

print()
print(f"{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
