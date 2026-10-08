"""학교 홍보 인터뷰 지역 필터 · 취업/진학 정보의 주요 취업처.

확인할 것:
  (1) /api/interviews?region= 이 그 지역 인터뷰만 준다. 기본(빈 값)은 전체
  (2) 지역은 포털 학교면 학교의 지역, 직접 입력한 학교면 인터뷰에 적은 지역. 없으면 '기타'
  (3) regions 는 거르기 전 전체 기준이라, 한 지역을 골라도 다른 버튼이 남는다
  (4) 관리자는 직접 입력 학교의 지역을 고를 수 있고, 목록에 없는 지역은 거절된다
  (5) 학교 계정(플래티넘)이 주요 취업처를 저장하면 공개 화면에 순서대로 나온다
  (6) 진학 통계가 없어도 주요 취업처가 있으면 학교 상세에 링크가 뜬다
  (7) 주요 취업처는 학교 계정(취업/진학 정보 탭)에서만 고친다. 관리자 학교 수정으로는 안 바뀐다
실행:  cd backend && python tests/region_employers.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "udj_region_employers.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AdmissionSetting, Coed, Plan, Role, School, User, Video  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()


def mk_school(name, region, plan=Plan.free):
    s = School(name=name, category="특성화고", region=region, address="주소", coed=Coed.coed,
               plan=plan, is_visible=True, phone="02")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def mk_user(email, role, school_id=None):
    u = User(email=email, password_hash=hash_password("p1234567"), name=email, role=role,
             school_id=school_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"Authorization": f"Bearer {create_access_token(u)}"}


S1 = mk_school("서울공고", "서울", Plan.platinum)
S2 = mk_school("경기공고", "경기")
S3 = mk_school("수원공고", "경기")
AH = mk_user("a@t.kr", Role.admin)
SH = mk_user("s@t.kr", Role.student)
PH = mk_user("p@t.kr", Role.school, S1.id)
v = Video(kind="longform", title="인터뷰 영상", file_path="x.mp4", is_public=False)
db.add(v)
db.commit()
VID, S1ID, S2ID, S3ID = v.id, S1.id, S2.id, S3.id
db.add(AdmissionSetting(school_id=S1ID, visibility="PUBLIC"))
db.commit()
db.close()
c = TestClient(app)

print("=== 1. 인터뷰 등록(지역) ===")
base = {"title": "t", "video_id": VID, "is_published": True}
for sid in (S1ID, S2ID, S3ID):
    r = c.post("/api/admin/interviews", headers=AH, json={**base, "school_id": sid, "title": f"i{sid}"})
    chk(f"학교 {sid} 인터뷰", r.status_code == 200, r.text)
r = c.post("/api/admin/interviews", headers=AH, json={**base, "school_id": None, "school_name": "부산분교",
                                                       "region": "부산", "title": "manual"})
chk("직접 입력 학교 + 지역", r.status_code == 200 and r.json()["school"]["region"] == "부산", r.text)
chk("관리 화면에 own_region", r.json()["own_region"] == "부산")
r = c.post("/api/admin/interviews", headers=AH, json={**base, "school_id": None, "school_name": "지역모름고",
                                                       "title": "noregion"})
chk("지역 없이도 등록", r.status_code == 200)
r = c.post("/api/admin/interviews", headers=AH, json={**base, "school_id": None, "school_name": "x",
                                                       "region": "화성시"})
chk("목록에 없는 지역 400", r.status_code == 400, r.text)
r = c.post("/api/admin/interviews", headers=AH, json={**base, "school_id": S2ID, "region": "부산", "title": "z"})
chk("포털 학교면 적은 지역을 무시하고 학교 지역", r.json()["school"]["region"] == "경기" and r.json()["own_region"] == "")
c.delete(f"/api/admin/interviews/{r.json()['id']}", headers=AH)

print("=== 2. 지역 필터 ===")
all_ = c.get("/api/interviews").json()
chk("전체 5개", len(all_["items"]) == 5 and all_["total"] == 5, str(len(all_["items"])))
chk("지역 버튼(학교 검색 순서)", [x["region"] for x in all_["regions"]] == ["서울", "부산", "경기", "기타"],
    str(all_["regions"]))
chk("지역별 개수", {x["region"]: x["count"] for x in all_["regions"]}["경기"] == 2)
g = c.get("/api/interviews", params={"region": "경기"}).json()
chk("경기만 2개", len(g["items"]) == 2 and all(x["school"]["region"] == "경기" for x in g["items"]))
chk("골라도 전체 지역 버튼 유지", len(g["regions"]) == 4 and g["total"] == 5)
chk("부산(직접 입력)", [x["title"] for x in c.get("/api/interviews", params={"region": "부산"}).json()["items"]] == ["manual"])
chk("기타 = 지역 모름", [x["title"] for x in c.get("/api/interviews", params={"region": "기타"}).json()["items"]] == ["noregion"])
chk("없는 지역은 빈 목록", c.get("/api/interviews", params={"region": "제주"}).json()["items"] == [])
chk("학교 필터와 함께", len(c.get("/api/interviews", params={"region": "경기", "school_id": S3ID}).json()["items"]) == 1)
chk("학교 지역을 바꾸면 인터뷰 지역도 따라감",
    c.patch(f"/api/admin/schools/{S3ID}", headers=AH, json={"region": "인천"}).status_code == 200
    and len(c.get("/api/interviews", params={"region": "인천"}).json()["items"]) == 1)

print("=== 3. 주요 취업처 ===")
chk("학생은 못 고침", c.put("/api/school-admin/admission/employers", headers=SH,
                            json={"items": ["a"]}).status_code == 403)
r = c.put("/api/school-admin/admission/employers", headers=PH,
          json={"items": [" 삼성전자 ", "SK하이닉스", "", "삼성전자", "현대자동차", "한국전력공사"]})
chk("저장(빈 줄·중복 빠짐, 순서 유지)", r.json()["items"] == ["삼성전자", "SK하이닉스", "현대자동차", "한국전력공사"], r.text)
chk("31곳은 422", c.put("/api/school-admin/admission/employers", headers=PH,
                       json={"items": [f"회사{i}" for i in range(31)]}).status_code == 422)
d = c.get("/api/school-admin/admission", headers=PH).json()
chk("관리 화면에 보임", d["major_employers"][0] == "삼성전자")
pub = c.get(f"/api/schools/{S1ID}/admission").json()
chk("공개 화면에 주요 취업처", pub["major_employers"] == ["삼성전자", "SK하이닉스", "현대자동차", "한국전력공사"],
    str(pub.get("major_employers")))
chk("안내문 이름 변경", pub["disclaimer"][0].startswith("본 취업/진학 정보"))
det = c.get(f"/api/schools/{S1ID}").json()
chk("진학 통계 없어도 취업처 있으면 링크", det["has_admission_info"] is True)
chk("학생·방문자 응답에는 관리용 칸 없음", det.get("major_employers") is None)
det2 = c.get(f"/api/schools/{S2ID}").json()
chk("취업처·통계 없는 학교는 링크 없음", det2["has_admission_info"] is False)

print("=== 4. 주요 취업처는 학교 화면에서만 ===")
r = c.patch(f"/api/admin/schools/{S2ID}", headers=AH, json={"major_employers": "LG전자"})
chk("관리자 학교 수정은 200(모르는 칸은 무시)", r.status_code == 200, r.text)
s2 = SessionLocal()
chk("관리자가 넣어도 안 들어감", not (s2.get(School, S2ID).major_employers or ""))
s2.close()
chk("관리자 응답에도 없음", c.get(f"/api/schools/{S2ID}", headers=AH).json().get("major_employers") is None)
chk("학생은 학교 수정 못 함", c.patch(f"/api/admin/schools/{S2ID}", headers=SH,
                                    json={"region": "서울"}).status_code == 403)

print(f"\n{sum(OK)}/{len(OK)} 통과")
sys.exit(0 if all(OK) else 1)
