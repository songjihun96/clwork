"""진학정보(플래티넘) 검사.

확인할 것:
  (1) 플래티넘이 아니면 관리 API 가 전부 403 이고 공개 페이지도 없다
  (2) 다른 학교 계정은 남의 행을 못 고치고 못 지운다
  (3) 공개 범위(전체/로그인/학생만/비공개)와 행별 공개 여부를 서버가 지킨다
  (4) 검증: 음수, 합계 초과, 연도 형식, 필수값 누락
  (5) 엑셀·CSV 업로드: 검사 → 확정, 오류 행 제외, 연도 교체
  (6) 집계: 비율 계산, 주요 대학 정렬, 필터, 최근 3년, 없는 연도는 채우지 않음
  (7) 이미 혜택 설정을 저장해 둔 운영 DB 에서도 새 혜택이 플래티넘에 켜진다
실행:  cd backend && python tests/admission.py
"""
import io
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "udj_admission_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import admission as adm  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Coed, Plan, Role, School, SchoolVerification, Setting,  # noqa: E402
                        User)

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


Y = date.today().year
db = SessionLocal()


def mk_school(name, plan, category="특성화고"):
    s = School(name=name, category=category, region="경기", address="수원", coed=Coed.coed,
               plan=plan, is_visible=True, phone="031")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


P = mk_school("플래티넘고", Plan.platinum)
Q = mk_school("프리미엄고", Plan.premium)
G = mk_school("일반플래티넘고", Plan.platinum, category="일반고")


def mk_user(email, role, school_id=None):
    u = User(email=email, password_hash=hash_password("p1234567"), name=email,
             role=role, school_id=school_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"Authorization": f"Bearer {create_access_token(u)}"}, u


HP, _ = mk_user("p@t.kr", Role.school, P.id)
HQ, _ = mk_user("q@t.kr", Role.school, Q.id)
HG, _ = mk_user("g@t.kr", Role.school, G.id)
HT, _ = mk_user("t@t.kr", Role.teacher, P.id)
HS_IN, stu_in = mk_user("s1@t.kr", Role.student)       # 인증된 재학생
HS_OUT, _ = mk_user("s2@t.kr", Role.student)           # 다른 학생
HA, _ = mk_user("a@t.kr", Role.admin)
db.add(SchoolVerification(user_id=stu_in.id, school_id=P.id, status="approved"))
db.commit()
PID, QID, GID = P.id, Q.id, G.id
db.close()
c = TestClient(app)

print("=== 1. 플래티넘 아님 → 관리 API 거부 ===")
r = c.get("/api/school-admin/admission/access", headers=HQ)
chk("access: allowed=False", r.status_code == 200 and r.json()["allowed"] is False, r.text)
for m, url, body in [
    ("get", "/api/school-admin/admission", None),
    ("put", f"/api/school-admin/admission/stats/{Y - 1}", {"total_graduates": 10}),
    ("post", "/api/school-admin/admission/records", {"rows": [{}]}),
    ("put", "/api/school-admin/admission/settings", {"visibility": "PUBLIC"}),
    ("get", "/api/school-admin/admission/export", None),
    ("get", "/api/school-admin/admission/template", None),
]:
    r = getattr(c, m)(url, headers=HQ, **({"json": body} if body is not None else {}))
    chk(f"프리미엄 {m.upper()} {url.split('/admission')[-1] or '/'} → 403", r.status_code == 403,
        str(r.status_code))
r = c.get(f"/api/schools/{QID}/admission")
chk("프리미엄 학교 공개 페이지 → 404", r.status_code == 404, str(r.status_code))
r = c.get("/api/school-admin/admission", headers=HS_IN)
chk("학생 토큰으로 관리 API → 403", r.status_code == 403)
r = c.get("/api/school-admin/admission")
chk("비로그인 관리 API → 401", r.status_code == 401)

print("=== 2. 플래티넘 기본 통계 입력·검증 ===")
r = c.get("/api/school-admin/admission/access", headers=HP)
chk("플래티넘 access: allowed=True", r.json()["allowed"] is True)
good = {"total_graduates": 120, "four_year_count": 45, "junior_college_count": 27,
        "other_higher_count": 0, "employment_count": 42, "other_count": 6,
        "same_field_count": 40, "diff_field_count": 32}
r = c.put(f"/api/school-admin/admission/stats/{Y - 1}", headers=HP, json=good)
chk("정상 통계 저장", r.status_code == 200, r.text)
chk("진학률 60.0%", r.json().get("admission_rate") == 60.0, r.text)
chk("4년제 37.5% · 전문대 22.5% · 취업 35.0%",
    r.json().get("four_year_rate") == 37.5 and r.json().get("junior_college_rate") == 22.5
    and r.json().get("employment_rate") == 35.0)
bad_cases = [
    ("졸업생 < 0", {**good, "total_graduates": -1}),
    ("진학자 < 0", {**good, "four_year_count": -3}),
    ("진학자 > 졸업생", {**good, "four_year_count": 200}),
    ("취업+진학+기타 > 졸업생", {**good, "employment_count": 60}),
    ("동일+비동일 > 진학자", {**good, "same_field_count": 80}),
]
for name, body in bad_cases:
    r = c.put(f"/api/school-admin/admission/stats/{Y - 1}", headers=HP, json=body)
    chk(f"거부: {name}", r.status_code == 422, str(r.status_code))
r = c.put("/api/school-admin/admission/stats/1990", headers=HP, json=good)
chk("거부: 연도 형식(1990)", r.status_code == 422)
r = c.put(f"/api/school-admin/admission/stats/{Y + 3}", headers=HP, json=good)
chk("거부: 미래 연도", r.status_code == 422)
for y, g4, gj, emp in [(Y - 2, 40, 28, 45), (Y - 3, 38, 30, 48)]:
    c.put(f"/api/school-admin/admission/stats/{y}", headers=HP, json={
        "total_graduates": 120, "four_year_count": g4, "junior_college_count": gj,
        "employment_count": emp, "other_count": 2})
# 5년 전 해는 입력하되 4년 전은 비워 둔다 → 추세에서 빈 해를 만들지 않아야 한다
c.put(f"/api/school-admin/admission/stats/{Y - 5}", headers=HP, json={
    "total_graduates": 100, "four_year_count": 30, "junior_college_count": 20,
    "employment_count": 45, "other_count": 5})

print("=== 3. 대학 행 입력 ===")
rows = [
    {"year": Y - 1, "university_name": "가나대학교", "university_type": "4년제", "region": "서울",
     "department_name": "컴퓨터공학과", "department_category": "IT/소프트웨어", "student_count": 8},
    {"year": Y - 1, "university_name": "다라대학교", "university_type": "4_YEAR", "region": "경기",
     "department_name": "경영학과", "department_category": "경상계열", "student_count": 6},
    {"year": Y - 1, "university_name": "마바전문대학", "university_type": "전문대",
     "region": "CAPITAL_AREA", "department_name": "전기과", "department_category": "공학",
     "student_count": 7, "admission_type": "특별전형"},
    {"year": Y - 1, "university_name": "가나대학교", "university_type": "4년제", "region": "서울",
     "department_name": "전자공학과", "department_category": "공학", "student_count": 2},
    {"year": Y - 1, "university_name": "사아대학교", "university_type": "4년제", "region": "부산",
     "department_name": "간호학과", "department_category": "보건", "student_count": 1},
]
r = c.post("/api/school-admin/admission/records", headers=HP, json={"rows": rows})
chk("5행 일괄 등록", r.status_code == 200 and len(r.json()) == 5, r.text)
chk("한글 라벨이 코드로 저장(4년제→4_YEAR, 경기→CAPITAL_AREA, 부산→YEONGNAM)",
    r.json()[0]["university_type"] == "4_YEAR" and r.json()[1]["region"] == "CAPITAL_AREA"
    and r.json()[4]["region"] == "YEONGNAM", r.text[:300])
rec_ids = [x["id"] for x in r.json()]
r = c.post("/api/school-admin/admission/records", headers=HP, json={"rows": [
    {**rows[0], "university_name": ""},
    {**rows[0], "university_type": ""},
    {**rows[0], "department_name": ""},
    {**rows[0], "student_count": -1},
    {**rows[0], "year": "20x5"},
]})
chk("오류 행이 있으면 전체 거부(422)", r.status_code == 422, r.text)
for word in ("대학명 누락", "대학 유형 누락", "학과명 누락", "진학자 수 < 0", "연도 형식 오류"):
    chk(f"오류 메시지 포함: {word}", word in r.text)
r = c.post("/api/school-admin/admission/records", headers=HP, json={"rows": [
    {**rows[0], "student_count": 200}]})
chk("대학별 인원 합계 > 졸업생 → 거부", r.status_code == 422 and "졸업생" in r.text, r.text)
r = c.put(f"/api/school-admin/admission/stats/{Y - 1}", headers=HP, json={**good, "total_graduates": 20,
          "four_year_count": 5, "junior_college_count": 5, "employment_count": 5, "other_count": 0,
          "same_field_count": None, "diff_field_count": None})
chk("이미 입력한 대학별 합계(24) > 새 졸업생 수(20) → 거부", r.status_code == 422, r.text)

print("=== 4. 다른 학교는 못 고친다 ===")
r = c.put(f"/api/school-admin/admission/records/{rec_ids[0]}", headers=HG, json={"student_count": 99})
chk("다른 플래티넘 학교 수정 → 404", r.status_code == 404, str(r.status_code))
r = c.delete(f"/api/school-admin/admission/records/{rec_ids[0]}", headers=HG)
chk("다른 플래티넘 학교 삭제 → 404", r.status_code == 404)
r = c.get("/api/school-admin/admission/records", headers=HG)
chk("다른 학교 목록에 우리 행이 안 보임", r.status_code == 200 and r.json() == [])
r = c.put(f"/api/school-admin/admission/records/{rec_ids[0]}", headers=HP, json={"student_count": 9})
chk("본인 학교 수정 가능", r.status_code == 200 and r.json()["student_count"] == 9, r.text)

print("=== 5. 공개 범위 ===")
r = c.get(f"/api/schools/{PID}/admission")
chk("설정 전(기본 비공개) → 방문자 404", r.status_code == 404, str(r.status_code))
r = c.get(f"/api/schools/{PID}/admission", headers=HT)
chk("우리 학교 선생님은 비공개여도 조회", r.status_code == 200)
r = c.get(f"/api/schools/{PID}/admission", headers=HA)
chk("관리자는 조회", r.status_code == 200)
r = c.get(f"/api/schools/{PID}", headers=HS_OUT)
chk("상세 has_admission_info=False(비공개)", r.json().get("has_admission_info") is False)

c.put("/api/school-admin/admission/settings", headers=HP, json={"visibility": "STUDENTS"})
chk("학생만: 비로그인 401", c.get(f"/api/schools/{PID}/admission").status_code == 401)
chk("학생만: 다른 학생 403",
    c.get(f"/api/schools/{PID}/admission", headers=HS_OUT).status_code == 403)
chk("학생만: 인증된 재학생 200",
    c.get(f"/api/schools/{PID}/admission", headers=HS_IN).status_code == 200)

c.put("/api/school-admin/admission/settings", headers=HP, json={"visibility": "MEMBERS"})
chk("로그인만: 비로그인 401", c.get(f"/api/schools/{PID}/admission").status_code == 401)
chk("로그인만: 아무 학생 200",
    c.get(f"/api/schools/{PID}/admission", headers=HS_OUT).status_code == 200)
r = c.get("/api/sitemap.xml")
chk("로그인만이면 사이트맵에 없음", f"/schools/{PID}/admission" not in r.text)

r = c.put("/api/school-admin/admission/settings", headers=HP, json={"visibility": "EVERYONE"})
chk("모르는 공개 범위 → 422", r.status_code == 422)
c.put("/api/school-admin/admission/settings", headers=HP, json={"visibility": "PUBLIC"})
r = c.get(f"/api/schools/{PID}/admission")
chk("전체 공개: 비로그인 200", r.status_code == 200, r.text[:200])
d = r.json()
chk("indexable=True", d["indexable"] is True)
r = c.get("/api/sitemap.xml")
chk("전체 공개면 사이트맵에 포함", f"/schools/{PID}/admission" in r.text)
r = c.get(f"/api/schools/{PID}")
chk("상세 has_admission_info=True", r.json().get("has_admission_info") is True)

print("=== 6. 집계 ===")
chk("기본 선택 연도 = 가장 최근 입력 연도", d["selected_year"] == str(Y - 1), d["selected_year"])
chk("요약: 졸업생 120 · 진학 72 · 60.0%",
    d["summary"]["total_graduates"] == 120 and d["summary"]["admission_count"] == 72
    and d["summary"]["admission_rate"] == 60.0)
chk("직업계고 판정(특성화고)", d["school_type"] == "VOCATIONAL_HIGH")
tops = d["top_universities"]
chk("주요 대학 1위 가나대학교 11명(9+2 합산)",
    tops and tops[0]["name"] == "가나대학교" and tops[0]["count"] == 11, str(tops[:2]))
chk("주요 학과 1위 컴퓨터공학과 9명",
    d["top_departments"][0]["name"] == "컴퓨터공학과" and d["top_departments"][0]["count"] == 9)
reg = {x["key"]: x["percent"] for x in d["region_distribution"]}
chk("권역: 서울 44.0% (11/25)", reg.get("SEOUL") == 44.0, str(reg))
years_in_trend = [t["year"] for t in d["trend"]]
chk("추세에 입력 안 한 연도는 없음", (Y - 4) not in years_in_trend and (Y - 5) in years_in_trend,
    str(years_in_trend))
chk("최근 3년: 3개년, 졸업생 360", d["recent3"]["year_count"] == 3
    and d["recent3"]["total_graduates"] == 360, str(d["recent3"]))
chk("최근 3년 수도권 비율은 대학별 입력 인원 기준",
    d["recent3"]["capital_area_basis"] == 25 and d["recent3"]["capital_area_ratio"] == 96.0,
    str(d["recent3"]))
chk("프로필 주요 대학 3개", len(d["profile"]["main_universities"]) == 3, str(d["profile"]))
chk("출처 문구 3줄", len(d["disclaimer"]) == 3)

r = c.get(f"/api/schools/{PID}/admission", params={"university_type": "JUNIOR_COLLEGE"})
chk("필터(전문대): 주요 대학이 전문대만",
    [u["name"] for u in r.json()["top_universities"]] == ["마바전문대학"], r.text[:300])
r = c.get(f"/api/schools/{PID}/admission", params={"region": "SEOUL", "department_category": "IT_SOFTWARE"})
chk("필터(서울+IT): 컴퓨터공학과만", [x["name"] for x in r.json()["top_departments"]] == ["컴퓨터공학과"])
r = c.get(f"/api/schools/{PID}/admission", params={"year": Y - 2})
chk("대학 행이 없는 연도는 주요 대학 비어 있음(지어내지 않음)",
    r.json()["top_universities"] == [] and r.json()["summary"]["year"] == Y - 2)
r = c.get(f"/api/schools/{PID}/admission", params={"year": "recent3"})
chk("year=recent3 요약은 3개년 합계", r.json()["summary"]["total_graduates"] == 360)

print("=== 7. 행별 비공개 · 소수 인원 가리기 ===")
c.put(f"/api/school-admin/admission/records/{rec_ids[4]}", headers=HP, json={"is_published": False})
r = c.get(f"/api/schools/{PID}/admission")
chk("비공개 행(사아대학교)은 공개 화면에서 빠짐",
    all(u["name"] != "사아대학교" for u in r.json()["top_universities"]))
c.put("/api/school-admin/admission/settings", headers=HP,
      json={"visibility": "PUBLIC", "small_count_threshold": 3})
r = c.get(f"/api/schools/{PID}/admission")
dept = {x["name"]: x for x in r.json()["top_departments"]}
chk("3명 미만 학과는 숫자 대신 masked", dept["전자공학과"]["count"] is None
    and dept["전자공학과"]["masked"] is True, str(dept.get("전자공학과")))
chk("3명 이상은 그대로", dept["컴퓨터공학과"]["count"] == 9)
c.put(f"/api/school-admin/admission/stats/{Y - 3}", headers=HP, json={
    "total_graduates": 120, "four_year_count": 38, "junior_college_count": 30,
    "employment_count": 48, "other_count": 2, "is_published": False})
r = c.get(f"/api/schools/{PID}/admission")
chk("비공개 연도는 연도 목록·추세에서 빠짐",
    (Y - 3) not in r.json()["years"] and all(t["year"] != Y - 3 for t in r.json()["trend"]))

print("=== 8. 취업 분야 ===")
r = c.put(f"/api/school-admin/admission/employment/{Y - 1}", headers=HP,
          json={"items": {"IT_SOFTWARE": 20, "MANUFACTURING": 22}})
chk("취업 분야 저장", r.status_code == 200, r.text)
r = c.put(f"/api/school-admin/admission/employment/{Y - 1}", headers=HP,
          json={"items": {"IT_SOFTWARE": 50}})
chk("취업 분야 합계 > 취업자 → 거부", r.status_code == 422)
r = c.put(f"/api/school-admin/admission/employment/{Y - 1}", headers=HP, json={"items": {"HACK": 1}})
chk("모르는 분야 → 거부", r.status_code == 422)
r = c.get(f"/api/schools/{PID}/admission")
chk("공개 화면에 취업 분야", {x["key"] for x in r.json()["employment_fields"]} == {"IT_SOFTWARE", "MANUFACTURING"})

print("=== 9. 엑셀·CSV 업로드 ===")
r = c.get("/api/school-admin/admission/template", headers=HP)
chk("xlsx 템플릿 다운로드", r.status_code == 200 and r.content[:2] == b"PK")
tmpl = adm.read_xlsx(r.content)
chk("템플릿을 다시 읽으면 머리글·예시 3행", tmpl[0][:7] == adm.TEMPLATE_HEADERS[:7] and len(tmpl) == 4,
    str(tmpl[:2]))
r = c.get("/api/school-admin/admission/template", params={"format": "csv"}, headers=HP)
chk("CSV 템플릿은 BOM 포함 UTF-8", r.content[:3] == b"\xef\xbb\xbf")

good_rows = [[Y - 2, f"대학{i}", "4년제", "서울", "학과", "공학", 1, ""] for i in range(10)]
bad_rows = [[Y - 2, "", "4년제", "서울", "학과", "공학", 1, ""],
            [Y - 2, "오류대", "몰라", "서울", "학과", "공학", 1, ""],
            ["abcd", "오류대2", "4년제", "서울", "학과", "공학", -2, ""]]
xlsx = adm.write_xlsx([("s", [adm.TEMPLATE_HEADERS] + good_rows + bad_rows)])
files = {"file": ("upload.xlsx", xlsx, "application/octet-stream")}
r = c.post("/api/school-admin/admission/import", headers=HP, files=files)
rep = r.json()
chk("검사: 총 13 · 정상 10 · 오류 3",
    rep["total"] == 13 and rep["valid"] == 10 and rep["error_count"] == 3, str(rep)[:300])
chk("오류 행 번호가 엑셀 행 번호(12~14)", [e["row"] for e in rep["errors"]] == [12, 13, 14],
    str([e["row"] for e in rep["errors"]]))
chk("검사만 했으면 저장 안 됨", rep["committed"] is False
    and not [x for x in c.get("/api/school-admin/admission/records", headers=HP,
                               params={"year": Y - 2}).json()])
r = c.post("/api/school-admin/admission/import", headers=HP, files=files, params={"commit": True})
chk("오류가 있으면 확정 거부", r.status_code == 422)
r = c.post("/api/school-admin/admission/import", headers=HP, files=files,
           params={"commit": True, "skip_errors": True})
chk("오류 행 제외하고 10행 저장", r.status_code == 200 and r.json()["inserted"] == 10, r.text[:200])
r = c.post("/api/school-admin/admission/import", headers=HP, files=files,
           params={"commit": True, "skip_errors": True, "replace": True})
chk("연도 교체: 기존 10행 지우고 10행", r.json().get("replaced") == 10 and r.json()["inserted"] == 10)
n = len(c.get("/api/school-admin/admission/records", headers=HP, params={"year": Y - 2}).json())
chk("교체 후 그 연도 10행", n == 10, str(n))

csv_text = "연도,대학명,대학유형,지역,학과,학과계열,진학자수\n" \
           f"{Y - 2},차카대학교,전문대학,대전,간호과,보건,3\n"
r = c.post("/api/school-admin/admission/import", headers=HP, params={"commit": True},
           files={"file": ("u.csv", csv_text.encode("cp949"), "text/csv")})
chk("CP949 CSV(한국어 엑셀 저장본) 업로드", r.status_code == 200 and r.json()["inserted"] == 1, r.text[:200])
big = [[Y - 2, "큰대학", "4년제", "서울", "학과", "공학", 500, ""]]
r = c.post("/api/school-admin/admission/import", headers=HP,
           files={"file": ("b.xlsx", adm.write_xlsx([("s", [adm.TEMPLATE_HEADERS] + big)]), "x")})
chk("업로드 합계 > 졸업생 → 일반 오류", r.json()["general_errors"], str(r.json())[:200])
r = c.post("/api/school-admin/admission/import", headers=HP,
           files={"file": ("x.txt", b"hello", "text/plain")})
chk("xlsx/csv 가 아니면 거부", r.status_code == 422)
r = c.post("/api/school-admin/admission/import", headers=HP,
           files={"file": ("x.xlsx", b"not a zip", "x")})
chk("깨진 xlsx 거부", r.status_code == 422)
r = c.post("/api/school-admin/admission/import", headers=HQ, files=files)
chk("프리미엄 학교 업로드 → 403", r.status_code == 403)

c.post("/api/school-admin/admission/records", headers=HP, json={"rows": [
    {"year": Y - 1, "university_name": "=HYPERLINK(\"x\")", "university_type": "기타",
     "region": "기타", "department_name": "학과", "department_category": "기타", "student_count": 1}]})
r = c.get("/api/school-admin/admission/export", params={"format": "csv"}, headers=HP)
chk("CSV 내보내기: 수식 주입 무력화", "'=HYPERLINK" in r.content.decode("utf-8-sig"))

print("=== 10. 대시보드 · 비교 · 관심 계열 ===")
r = c.get("/api/school-admin/admission", headers=HP)
chk("대시보드 200", r.status_code == 200)
row = next(x for x in r.json()["years"] if x["year"] == Y - 1)
chk("대시보드: 등록 대학 수·학과 수", row["universities"] >= 4 and row["departments"] >= 4, str(row))
chk("대시보드: 주요대학만 적어 합계가 적어도 경고 없음",
    not any("주요대학" in w or "대학별" in w for w in row["warnings"]), str(row["warnings"]))
chk("최종 수정일 있음", bool(r.json()["last_updated"]))
r = c.get("/api/admission/compare", params={"ids": f"{PID},{QID},{GID}"})
cmp = {x["school"]["id"]: x for x in r.json()}
chk("비교: 공개 학교는 지표 포함", cmp[PID]["available"] and cmp[PID]["recent3"]["available"])
chk("비교: 플래티넘 아닌 학교는 볼 수 없음 표시", cmp[QID]["available"] is False)
chk("비교: 기준 연도 포함", bool(cmp[PID]["recent3"]["years"]))
r = c.get("/api/admission/interest", params={"category": "IT_SOFTWARE", "ids": f"{PID},{QID}"})
chk("관심 계열: 볼 수 있는 학교만, IT 9명", len(r.json()) == 1 and r.json()[0]["count"] == 9, r.text)

print("=== 11. 일반고 · 플랜 일시정지 · 데이터 없음 ===")
c.put("/api/school-admin/admission/settings", headers=HG, json={"visibility": "PUBLIC"})
r = c.get(f"/api/schools/{GID}/admission")
chk("일반고 판정", r.json()["school_type"] == "GENERAL_HIGH")
chk("데이터 없으면 '최근 3년 데이터를 확인할 수 없습니다.'",
    r.json()["profile"]["message"] == "최근 3년 데이터를 확인할 수 없습니다.")
chk("데이터 없으면 요약 None", r.json()["summary"] is None)
chk("데이터 없으면 사이트맵 제외", f"/schools/{GID}/admission" not in c.get("/api/sitemap.xml").text)
db = SessionLocal()
db.get(School, PID).plan_paused = True
db.commit()
chk("일시정지 → 관리 API 403",
    c.get("/api/school-admin/admission", headers=HP).status_code == 403)
chk("일시정지 → 공개 페이지 404", c.get(f"/api/schools/{PID}/admission").status_code == 404)
db.get(School, PID).plan_paused = False
db.commit()

print("=== 12. 저장된 혜택 설정이 있어도 새 혜택은 플래티넘 기본으로 켜진다 ===")
# 이 기능 이전에 관리자가 혜택을 저장한 운영 DB 흉내: 옛 키만 들어 있음
import json  # noqa: E402
db.add(Setting(key="plan_perks_platinum", value=json.dumps(sorted(
    ["search_upper", "search_pin", "search_top", "stats_views"]))))
db.commit()
db.close()
chk("옛 설정만 있어도 플래티넘 접근 가능",
    c.get("/api/school-admin/admission/access", headers=HP).json()["allowed"] is True)
r = c.patch("/api/admin/plan-perks/platinum", headers=HA, json={"keys": ["search_top"]})
chk("관리자가 새 목록으로 저장(진학정보 끔)", r.status_code == 200, r.text)
chk("관리자가 끈 뒤에는 꺼짐",
    c.get("/api/school-admin/admission/access", headers=HP).json()["allowed"] is False)
c.patch("/api/admin/plan-perks/platinum", headers=HA, json={"reset": True})
chk("기본값 복원하면 다시 켜짐",
    c.get("/api/school-admin/admission/access", headers=HP).json()["allowed"] is True)
r = c.get("/api/admin/perk-catalog", headers=HA)
chk("관리자 혜택 목록에 진학정보 표시", any(p["key"] == "admission_stats" for p in r.json()["perks"]))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
