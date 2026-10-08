"""영상 시연용 테스트 DB 를 처음부터 다시 만든다. 모든 학교·사람·숫자는 가상이다.

    .venv/Scripts/python.exe seed_demo.py

- DB: data/demo.db (표를 모두 지우고 새로 만든다. 서버가 켜져 있어도 된다). 운영 DB 와 무관하다.
- 테스트 계정 비밀번호는 무작위로 만들어 data/demo_accounts.json 에만 적는다(커밋하지 않는다).
- 이메일은 모두 예약 도메인(example.com)이라 실제 메일이 나가지 않는다.
"""
import json
import secrets
import string
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_backend  # noqa: E402  (경로·환경변수 설정)

database = run_backend.patch_engine()

import app.main  # noqa: E402,F401  (테이블 생성·마이그레이션)

# 서버가 켜져 있어도 다시 만들 수 있게 파일을 지우지 않고 표를 비운 뒤 새로 만든다.
database.Base.metadata.drop_all(bind=database.engine)
database.Base.metadata.create_all(bind=database.engine)
from app.auth import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    OrderStatus, PlanOrder,
    AdmissionEmployment, AdmissionEvent, AdmissionRecord, AdmissionSetting, AdmissionStat,
    Coed, Favorite, Inquiry, InquiryStatus, Plan, Role, School, SchoolView, Setting, User,
)

TODAY = date(2026, 10, 2)


def pw(n=14):
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(n))


db = database.SessionLocal()

# 운영 사이트와 같은 메뉴 상태(설명회·인터뷰 메뉴 숨김)
for k, v in {"nav_special": "false", "nav_interviews": "false"}.items():
    db.add(Setting(key=k, value=v))

# 요금제 가격·혜택은 운영 사이트의 공개 값(/api/meta)과 같게 맞춘다 — 코드 기본값과 다르다.
# 받아오지 못하면 2026-10-02 에 확인한 값을 쓴다.
PLAN_SNAPSHOT = {
    "basic": (149000, 1390000, ["참가 행사 일정 등록", "학교 설명회 일정 등록"]),
    "premium": (249000, 2390000, ["일반 학교보다 상단 노출", "검색 결과 상위 고정", "검색 카드 색상 강조",
                                  "참가 행사 일정 등록", "학교 설명회 일정 등록", "추천 학교 배너 노출"]),
    "platinum": (299000, 2900000, ["일반 학교보다 상단 노출", "검색 결과 상위 고정", "검색 결과 최상단 고정",
                                   "검색 카드 색상 강조", "참가 행사 일정 등록", "학교 설명회 일정 등록",
                                   "추천 학교 배너 노출", "메인 소식 우선 노출", "조회수 통계", "일자별 상세 통계",
                                   "즐겨찾기 전환 분석", "취업/진학 정보 분석·공개 페이지"]),
}
try:
    import urllib.request
    live = json.load(urllib.request.urlopen("https://udjschool.ggm.kr/api/meta", timeout=10))
    PLAN_SNAPSHOT = {p["plan"]: (p["price_per_month"], p["price_per_year"], p["perks"])
                     for p in live["plans"] if p["plan"] != "free"}
    print("plan prices/perks: live /api/meta")
except Exception as e:  # noqa: BLE001
    print("plan prices/perks: snapshot 2026-10-02 (", e, ")")
label_to_key = {label: key for key, label in app.main.PERK_CATALOG}
for plan_name, (month, year, perks) in PLAN_SNAPSHOT.items():
    db.add(Setting(key=f"plan_price_{plan_name}", value=str(month)))
    db.add(Setting(key=f"plan_price_year_{plan_name}", value=str(year)))
    app.main.set_plan_perk_keys(db, Plan(plan_name), [label_to_key[x] for x in perks if x in label_to_key])

# ── 가상 학교 ──────────────────────────────────────────────
main_school = School(
    name="예시미래산업고등학교", category="특성화고", region="경기",
    address="경기도 예시시 미래로 100 (가상 주소)", coed=Coed.coed, dormitory=None,
    foundation="공립", phone="031-000-0000", website="https://example.com",
    latitude=37.40, longitude=127.10,
    departments="스마트전기과\n반도체장비과\nAI소프트웨어과\n디자인콘텐츠과",
    established_year=1985, student_count=None, employment_rate=None,
    plan=Plan.platinum, plan_expires_at=TODAY + timedelta(days=300),
    plan_is_free_trial=False,
    view_count=0,
)
others = [
    School(name="예시디자인고등학교", category="특성화고", region="경기",
           address="경기도 예시시 디자인로 20 (가상 주소)", coed=Coed.coed, foundation="사립",
           phone="031-000-0001", website="https://example.com", latitude=37.38, longitude=127.12,
           departments="시각디자인과\n영상콘텐츠과\n웹툰애니메이션과", established_year=1992),
    School(name="예시마이스터고등학교", category="마이스터고", region="경기",
           address="경기도 예시시 산업로 5 (가상 주소)", coed=Coed.coed, dormitory=True, foundation="공립",
           phone="031-000-0002", website="https://example.com", latitude=37.42, longitude=127.08,
           departments="반도체설비과\n자동화설비과", established_year=2012),
    School(name="예시비즈니스고등학교", category="특성화고", region="서울",
           address="서울특별시 예시구 경영로 7 (가상 주소)", coed=Coed.girls,
           foundation="사립", phone="02-000-0003", website="https://example.com",
           latitude=37.55, longitude=126.98, departments="금융경영과\n세무회계과\n마케팅과", established_year=1970),
]
from app.dept_fields import to_storage  # noqa: E402
for s in [main_school, *others]:
    s.dept_fields = to_storage(s.departments)   # 학과 계열 검색용 캐시(실서비스와 같은 방식)
db.add(main_school)
db.add_all(others)
db.flush()

# ── 테스트 계정 ────────────────────────────────────────────
accounts = {}


def make_user(key, **kw):
    p = pw()
    u = User(password_hash=hash_password(p), is_active=True, privacy_consent_at=datetime.utcnow(), **kw)
    db.add(u)
    db.flush()
    accounts[key] = {"email": kw["email"], "password": p, "role": kw["role"].value, "name": kw["name"]}
    return u


school_user = make_user(
    "school", email="jinro.demo@example.com", name="진로부 담당", role=Role.school,
    school_id=main_school.id, phone="01000000000", must_change_password=True,
)
student = make_user(
    "student", email="student.demo@example.com", name="김예시", role=Role.student,
    phone="01000000001", birth_date=date(2010, 5, 1),
)
# 즐겨찾기 통계용 가상 학생(로그인하지 않는다)
extra = [make_user(f"s{i}", email=f"student{i}.demo@example.com", name=f"가상학생{i}",
                   role=Role.student, phone=f"0100000010{i}", birth_date=date(2010, 3, i))
         for i in range(2, 8)]

# 즐겨찾기 + 메모
db.add(Favorite(user_id=student.id, school_id=main_school.id, memo="반도체장비과 · 10월 설명회 가 보기"))
db.add(Favorite(user_id=student.id, school_id=others[1].id, memo="기숙사 있음"))
for u in extra:
    db.add(Favorite(user_id=u.id, school_id=main_school.id))

# ── 플랜 신청 내역(가상) — 입금 확인 후 관리자 승인된 상태 ──────
db.add(PlanOrder(school_id=main_school.id, requested_by=school_user.id, plan=Plan.platinum, months=12,
                 amount=PLAN_SNAPSHOT["platinum"][1], status=OrderStatus.approved, deposit_code="UDJ-DEMO",
                 tax_manager="가상행정", tax_email="office.demo@example.com",
                 created_at=datetime(2026, 7, 20, 10, 0), paid_at=datetime(2026, 7, 24, 15, 0),
                 handled_at=datetime(2026, 7, 29, 9, 0)))

# ── 학교 일정 ──────────────────────────────────────────────
db.add(AdmissionEvent(school_id=main_school.id, kind="briefing", title="2027학년도 신입생 입학설명회",
                      start_date=date(2026, 10, 24), start_time="14:00", end_time="16:00",
                      location="본관 3층 시청각실 (가상)", description="학과 소개와 실습실 투어를 진행합니다."))
db.add(AdmissionEvent(school_id=others[1].id, kind="admission", title="마이스터고 체험의 날",
                      start_date=date(2026, 10, 31), start_time="10:00",
                      location="실습동 (가상)", description="반도체 설비 실습 체험"))

# ── 조회 기록(최근 14일) ───────────────────────────────────
daily = [18, 22, 19, 25, 31, 27, 24, 29, 35, 33, 30, 38, 41, 36]
for i, c in enumerate(daily):
    db.add(SchoolView(school_id=main_school.id, viewed_on=TODAY - timedelta(days=13 - i), count=c))
main_school.view_count = 1284

# ── 문의 (가상 문의자) ─────────────────────────────────────
inq = [
    ("이가상", "parent1@example.com", "반도체장비과는 1학년 때부터 실습을 하나요? 실습실 견학이 가능한지 궁금합니다.", 2),
    ("박예시", "student.park@example.com", "입학설명회에 학부모와 같이 가도 되나요? 주차 공간이 있는지도 알려 주세요.", 1),
    ("", "q.anon@example.com", "AI소프트웨어과에서 취득할 수 있는 자격증을 알고 싶습니다.", 0),
]
for name, email, q, days in inq:
    db.add(Inquiry(school_id=main_school.id, asker_name=name, contact_email=email, contact_phone="",
                   question=q, privacy_consent=True, status=InquiryStatus.pending,
                   created_at=datetime(2026, 10, 2, 9, 0) - timedelta(days=days)))

# ── 취업/진학 정보 (가상 숫자) ─────────────────────────────
for year, (tot, four, jun, oth_h, emp, oth, same, diff) in {
    2025: (176, 34, 44, 5, 76, 17, 55, 28),
    2026: (182, 38, 46, 6, 74, 18, 60, 30),
}.items():
    db.add(AdmissionStat(school_id=main_school.id, year=year, total_graduates=tot, four_year_count=four,
                         junior_college_count=jun, other_higher_count=oth_h, employment_count=emp,
                         other_count=oth, same_field_count=same, diff_field_count=diff))
records = [
    ("예시과학기술대학교", "4_YEAR", "CAPITAL_AREA", "전기공학과", "ENGINEERING", 9),
    ("예시대학교", "4_YEAR", "SEOUL", "컴퓨터공학과", "IT_SOFTWARE", 7),
    ("샘플공과대학교", "4_YEAR", "CHUNGCHEONG", "반도체공학과", "ENGINEERING", 6),
    ("가상폴리텍대학", "JUNIOR_COLLEGE", "CAPITAL_AREA", "반도체설비과", "ENGINEERING", 14),
    ("예시전문대학", "JUNIOR_COLLEGE", "CAPITAL_AREA", "소프트웨어과", "IT_SOFTWARE", 11),
    ("샘플전문대학", "JUNIOR_COLLEGE", "SEOUL", "디자인과", "ARTS", 8),
]
for uni, t, reg, dept, cat, n in records:
    db.add(AdmissionRecord(school_id=main_school.id, year=2026, university_name=uni, university_type=t,
                           region=reg, department_name=dept, department_category=cat, student_count=n))
for field, n in {"MANUFACTURING": 26, "ELECTRONICS": 21, "IT_SOFTWARE": 14, "PUBLIC": 7, "SERVICE": 6}.items():
    db.add(AdmissionEmployment(school_id=main_school.id, year=2026, field=field, count=n))
main_school.major_employers = "예시전자(가상)\n샘플반도체(가상)\n가상에너지(가상)"
db.add(AdmissionSetting(school_id=main_school.id, visibility="PUBLIC"))

db.commit()
out = HERE / "data" / "demo_accounts.json"
out.write_text(json.dumps({"school_id": main_school.id, "accounts": accounts}, ensure_ascii=False, indent=2),
               encoding="utf-8")
print("seeded:", run_backend.DB_FILE, "| school id", main_school.id, "| accounts →", out)
