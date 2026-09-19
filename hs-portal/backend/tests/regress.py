"""UDJ 기존 기능 회귀. 배포 전에 돌려 본다."""
import os,sys,json
os.environ["DATABASE_URL"]="sqlite:////tmp/ur.db"; os.environ["SECRET_KEY"]="x"
os.environ["PARTNER_SECRET"]="test-partner-secret"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/ur.db"):
    os.remove("/tmp/ur.db")
sys.path.insert(0,".")
from fastapi.testclient import TestClient
from app.main import app
from app import mailer
from app.database import SessionLocal
from app.models import *
from app.auth import hash_password, create_access_token
from datetime import datetime, date, timedelta
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
sc=School(name="근명고등학교",category="특성화고",region="경기",address="양주시 고암동",
          coed=Coed.coed,departments="기계과\n전기과\n소프트웨어과",
          latitude=37.79,longitude=127.05,is_visible=True,phone="031-000-0000")
db.add(sc); db.commit(); db.refresh(sc); SID=sc.id
adm=User(email="a@t.kr",password_hash=hash_password("p1234567"),name="관리자",role=Role.admin)
tea=User(email="t@t.kr",password_hash=hash_password("p1234567"),name="김선생",
         role=Role.teacher,school_id=SID,class_name="2-3")
stu=User(email="s@t.kr",password_hash=hash_password("p1234567"),name="홍길동",
         role=Role.student,school_id=SID)
sch=User(email="sc@t.kr",password_hash=hash_password("p1234567"),name="학교",
         role=Role.school,school_id=SID)
for u in (adm,tea,stu,sch): db.add(u)
db.commit(); [db.refresh(u) for u in (adm,tea,stu,sch)]
AH={"Authorization":f"Bearer {create_access_token(adm)}"}
TH={"Authorization":f"Bearer {create_access_token(tea)}"}
SH={"Authorization":f"Bearer {create_access_token(stu)}"}
CH={"Authorization":f"Bearer {create_access_token(sch)}"}
db.close()
c=TestClient(app)

print("=== 로그인·계정 ===")
r=c.post("/api/auth/login", json={"email":"s@t.kr","password":"p1234567"})
chk("로그인", r.status_code==200 and r.json().get("access_token"), str(r.json())[:80])
chk("잘못된 비밀번호 거부", c.post("/api/auth/login",
    json={"email":"s@t.kr","password":"wrong"}).status_code in (400,401))
chk("내 정보", c.get("/api/auth/me", headers=SH).status_code==200)

print("=== 학교 검색·상세 ===")
r=c.get("/api/schools", params={"page":1,"size":20})
chk("검색", r.status_code==200 and r.json()["total"]>=1, str(r.json())[:80])
chk("지역 거르기", c.get("/api/schools", params={"region":"경기"}).status_code==200)
chk("이름 검색", c.get("/api/schools", params={"q":"근명"}).json()["total"]>=1)
chk("상세", c.get(f"/api/schools/{SID}").status_code==200)
chk("조회수 셈", c.post(f"/api/schools/{SID}/view").status_code==200)
chk("없는 학교", c.get("/api/schools/99999").status_code==404)

print("=== 진로 테스트 ===")
q=c.get("/api/quiz/questions")
# 36문항 5점 척도. 6축 × 6문항으로 고르게 물어본다.
chk("문항", q.status_code==200 and len(q.json()["questions"])==36,
    str(len(q.json().get("questions",[]))))
chk("척도 있음", q.json()["questions"][0].get("scale"),
    str(q.json()["questions"][0])[:80])
chk("seed 있음", isinstance(q.json().get("seed"), int))
chk("거리 선택지 km", "km" in q.json()["time_options"][0]["label"], q.json()["time_options"][0]["label"])
# 모두 '매우 그렇다'(5) 로 답한다.
r=c.post("/api/quiz/result", json={"answers":["5"]*36,"seed":q.json()["seed"],
  "lat":37.79,"lng":127.05,"location_label":"경기도 양주시","commute_time":"any"})
chk("결과", r.status_code==200, str(r.json())[:100])
chk("학교 추천", len(r.json().get("schools",[]))>=1,
    f"{len(r.json().get('schools',[]))}곳 · 계열 "
    + str([g["label"] for g in r.json().get("departments",[])][:2]))
chk("위치 없이도", c.post("/api/quiz/result",
    json={"answers":["3"]*36,"commute_time":"any"}).status_code==200)
chk("세부 점수 있음", "sub_scores" in r.json(), str(list(r.json()))[:100])
chk("확신도 있음", r.json().get("confidence") in ("high","close"), str(r.json().get("confidence")))
chk("동일 응답 신뢰도 경고", r.json().get("quality",{}).get("reliable") is False,
    str(r.json().get("quality")))
chk("다양한 응답은 신뢰도 정상",
    c.post("/api/quiz/result", json={"answers":[str((i%5)+1) for i in range(36)],
      "commute_time":"any"}).json().get("quality",{}).get("reliable") is True)

print("=== 즐겨찾기·후기·문의 ===")
chk("즐겨찾기 추가", c.post("/api/favorites", json={"school_id":SID},
    headers=SH).status_code==200)
chk("즐겨찾기 목록", len(c.get("/api/favorites", headers=SH).json())>=1)
chk("즐겨찾기 해제", c.delete(f"/api/favorites/{SID}", headers=SH).status_code==200)
r=c.post(f"/api/schools/{SID}/inquiries", json={
  "contact_email":"q@t.kr","contact_phone":"010-1234-5678",
  "question":"기숙사 신청은 어떻게 하나요?","privacy_consent":True})
chk("문의 접수", r.status_code==200, str(r.json())[:80])
chk("연락처 없으면 거부", c.post(f"/api/schools/{SID}/inquiries", json={
  "contact_email":"q@t.kr","question":"문의합니다","privacy_consent":True}).status_code==422)

print("--- 문의가 들어오면 학교에 알림 메일 ---")
# 알림 주소는 로그인 계정 메일과 따로 받는다. 비어 있으면 안 보낸다.
sent = []
_real_send = mailer.send_email
mailer.send_email = lambda cfg, to, subj, body, **kw: (sent.append((to, subj, body)) or (True, ""))
_real_cfg = mailer.system_config
mailer.system_config = lambda: mailer.MailConfig(
    host="smtp.test", port=587, username="u", password="p", sender="portal@test.kr")

chk("주소를 안 넣으면 알림 안 감", (
    c.post(f"/api/schools/{SID}/inquiries", json={
        "contact_email": "q1@t.kr", "contact_phone": "010-1234-5678",
        "question": "알림 없이 들어온 문의입니다", "privacy_consent": True,
    }).status_code == 200 and not sent), str(sent))

r = c.put("/api/school-admin/profile", headers=CH,
          json={"inquiry_notify_email": "teacher@school.kr"})
chk("알림 주소 저장", r.status_code == 200, r.text)
chk("잘못된 주소는 거절", c.put("/api/school-admin/profile", headers=CH,
    json={"inquiry_notify_email": "not-an-email"}).status_code == 422)
chk("저장된 주소가 프로필에 보임",
    c.get("/api/school-admin/profile", headers=CH).json().get("inquiry_notify_email")
    == "teacher@school.kr")

r = c.post(f"/api/schools/{SID}/inquiries", json={
    "asker_name": "김학생", "contact_email": "secret@t.kr",
    "contact_phone": "010-9999-8888",
    "question": "기숙사 신청 방법이 궁금합니다", "privacy_consent": True,
})
chk("문의 접수 200", r.status_code == 200, r.text)
chk("알림 메일 1통", len(sent) == 1, str(sent))
to, subj, body = sent[-1] if sent else ("", "", "")
chk("설정한 주소로 감", to == "teacher@school.kr", to)
chk("제목에 학교 이름", "근명고등학교" in subj, subj)
chk("본문에 문의 내용", "기숙사 신청 방법" in body, body[:120])
chk("본문에 보낸 사람 이름", "김학생" in body)
# 알림은 '확인해 보라'는 신호다. 연락처까지 메일로 흘리지 않는다.
chk("본문에 문의자 이메일 없음", "secret@t.kr" not in body, body[:200])
chk("본문에 문의자 전화번호 없음", "010-9999-8888" not in body)

r = c.put("/api/school-admin/profile", headers=CH, json={"inquiry_notify_email": ""})
chk("빈 값으로 알림 끄기", r.status_code == 200, r.text)
sent.clear()
c.post(f"/api/schools/{SID}/inquiries", json={
    "contact_email": "q2@t.kr", "contact_phone": "010-1111-2222",
    "question": "알림을 끈 뒤 들어온 문의", "privacy_consent": True})
chk("끈 뒤에는 안 감", not sent, str(sent))

mailer.send_email = _real_send
mailer.system_config = _real_cfg

print("=== 공개 정보 ===")
for path in ("/api/home", "/api/terms", "/api/notices", "/api/articles",
             "/api/sigungu", "/api/verify-config", "/api/geo-config"):
    params = {"region": "경기"} if path.endswith("sigungu") else None
    chk(path, c.get(path, params=params).status_code in (200, 404),
        str(c.get(path, params=params).status_code))

print("=== 관리자 ===")
chk("통계", c.get("/api/admin/stats", headers=AH).status_code==200)
r=c.get("/api/admin/stats/export", headers=AH)
chk("영업 CSV", r.status_code==200 and len(r.content)>500, str(r.status_code))
txt=r.content.decode("utf-8-sig")
for want in ("우선 영업 대상","노출은 많은데","지역별 수요 대비 공급"):
    chk(f"CSV '{want}'", want in txt)
# 학교 목록은 공개 검색을 쓴다. /api/admin/schools 는 등록용(POST)이다.
chk("학교 등록 권한", c.post("/api/admin/schools", json={}, headers=AH).status_code in (400,422))
chk("계정 관리", c.get("/api/admin/users", headers=AH).status_code==200)
chk("학생은 관리자 API 못 씀", c.get("/api/admin/stats", headers=SH).status_code==403)

print("=== 학교 담당자 ===")
chk("우리 학교", c.get("/api/school-admin/school", headers=CH).status_code in (200,404))
# 학생에게는 담당 학교가 없어 404 로 막힌다. 어느 쪽이든 못 본다.
chk("학생은 못 봄", c.get("/api/school-admin/school",
    headers=SH).status_code in (403,404))

print("=== 대표 이미지 업로드 ===")
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes-for-test\xff\xd9"
r = c.post("/api/school-admin/hero-image", files={"file": ("t.jpg", FAKE_JPEG_BYTES, "image/jpeg")}, headers=CH)
chk("업로드 성공", r.status_code == 200 and r.json().get("url", "").startswith("/api/uploads/hero_"), str(r.json())[:120])
hero_url = r.json().get("url")
chk("학생은 못 올림", c.post("/api/school-admin/hero-image",
    files={"file": ("t.jpg", FAKE_JPEG_BYTES, "image/jpeg")}, headers=SH).status_code == 403)
chk("확장자 아닌 파일은 거부", c.post("/api/school-admin/hero-image",
    files={"file": ("t.txt", b"hi", "text/plain")}, headers=CH).status_code == 400)
r = c.put("/api/school-admin/profile", json={"hero_image": hero_url}, headers=CH)
chk("업로드한 URL로 프로필 저장 가능(상대경로 허용)", r.status_code == 200, str(r.json())[:120])

print("=== 선생님 ===")
chk("학급 목록", c.get("/api/teacher/class-options", headers=TH).status_code==200)
chk("학생은 못 씀", c.get("/api/teacher/class-options", headers=SH).status_code==403)

print("=== 계정 검색 — 다른 학교 학생은 안 보여야 한다 ===")
db=SessionLocal()
sc2=School(name="저쪽고등학교",category="특성화고",region="서울",address="b",
          coed=Coed.coed,departments="디자인과",latitude=37.5,longitude=127.0,is_visible=True)
db.add(sc2); db.commit(); db.refresh(sc2); SID2=sc2.id
other=User(email="etc-uniq@t.kr",password_hash=hash_password("p1234567"),
          name="다른학교유일이름",role=Role.student,school_id=SID2)
other_tea=User(email="etc-tea-uniq@t.kr",password_hash=hash_password("p1234567"),
          name="저쪽학교유일교사",role=Role.teacher,school_id=SID2)
db.add(other); db.add(other_tea); db.commit()
db.close()
r=c.get("/api/teacher/students/search", params={"q":"다른학교유일이름"}, headers=TH).json()
chk("선생님 검색 — 다른 학교 학생 안 나옴", all(u["name"]!="다른학교유일이름" for u in r), str(r))
# 선생님 계정 검색·부여는 기록해 화면으로 옮겼다 — 기록해 서버가 이 partner
# API(X-Partner-Secret 인증, 학교 JWT 아님)를 통해 대신 부른다.
PH={"X-Partner-Secret":"test-partner-secret"}
r=c.get(f"/api/partner/schools/{SID}/teacher-candidates", params={"q":"다른학교유일이름"}, headers=PH).json()
chk("선생님 계정 검색(partner) — 다른 학교 학생 안 나옴", all(u["name"]!="다른학교유일이름" for u in r), str(r))
r=c.get(f"/api/partner/schools/{SID}/teacher-candidates", params={"q":"김선생"}, headers=PH).json()
chk("선생님 계정 검색(partner) — 우리 학교 선생님은 그대로 나옴", any(u["name"]=="김선생" for u in r), str(r))
r=c.get(f"/api/partner/schools/{SID}/teacher-candidates", params={"q":"저쪽학교유일교사"}, headers=PH).json()
chk("선생님 계정 검색(partner) — 다른 학교 선생님은 중복 신청 확인용으로 여전히 나옴(other_school 표시)",
    any(u["name"]=="저쪽학교유일교사" and u["other_school"] for u in r), str(r))
chk("선생님 계정 검색(partner) — 비밀키 없으면 거부",
    c.get(f"/api/partner/schools/{SID}/teacher-candidates", params={"q":"김선생"}).status_code in (401,503))

print("=== 계열 분류 ===")
from app import dept_fields as df
chk("기계과", "machine" in (df.to_storage("기계과") or ""))
chk("모빌리티과", "machine" in (df.to_storage("모빌리티모터스과") or ""))
chk("스마트양식과는 농림", "agri" in (df.to_storage("스마트양식과") or ""),
    df.to_storage("스마트양식과"))
chk("양식조리과는 조리", "food" in (df.to_storage("양식조리과") or ""),
    df.to_storage("양식조리과"))
print("--- 상세정보 초기화가 남길 것은 남기는가 ---")
# 다시 채우는 비용이 큰 값은 초기화로 날아가면 안 된다. 학과는 NEIS 에서
# (import_neis --majors), 기숙사 여부는 import_dormitory 로 받아오고,
# 대표 이미지는 학교가 올린 파일이라 지우면 되돌릴 길이 없다. 계열 검색이
# 쓰는 dept_fields 캐시도 같이 남아야 학과만 보이고 검색엔 안 잡히는
# 어긋난 상태가 안 생긴다.
r = c.put("/api/school-admin/profile", headers=CH, json={
    "intro": "지울 소개", "facilities": "지울 시설",
    "youtube_urls": "https://youtu.be/dQw4w9WgXcQ",
    "student_count": 500,
    "hero_image": "/api/uploads/hero-test.jpg", "dormitory": True,
})
chk("초기화 전 상세정보 채움", r.status_code == 200, r.text)
r = c.post(f"/api/admin/schools/{SID}/reset-profile", headers=AH)
chk("초기화 200", r.status_code == 200, r.text)
d = c.get(f"/api/schools/{SID}").json()
chk("학과는 그대로", d["departments"] == ["기계과", "전기과", "소프트웨어과"],
    str(d["departments"]))
chk("계열 검색 캐시도 그대로", len(c.get("/api/schools?dept_field=it").json()["items"]) >= 1)
chk("대표 이미지도 그대로", d.get("hero_image") == "/api/uploads/hero-test.jpg",
    str(d.get("hero_image")))
chk("기숙사 여부도 그대로", d.get("dormitory") is True, str(d.get("dormitory")))
chk("소개는 비워짐", d["intro"] == "", d["intro"])
chk("시설도 비워짐", d["facilities"] == "")
chk("학생 수도 비워짐", d["student_count"] is None)
chk("소개 영상도 비워짐", d.get("youtube_videos") == [], str(d.get("youtube_videos")))

print("--- 종합고 계열 ---")
# 나이스는 종합고를 따로 안 준다. 일반고·특성화고로 섞여 들어오므로 이름으로
# 가려낸다. 이 포털이 다루는 범위(직업계고)에도 들어가야 진로 테스트 추천과
# 나이스 수집 기본 범위에서 빠지지 않는다.
from app.import_neis import VOCATIONAL_CATEGORIES, derive_category
from app.main import CATEGORY_ORDER
chk("종합고가 직업계고 범위에 있음", "종합고" in VOCATIONAL_CATEGORIES,
    str(VOCATIONAL_CATEGORIES))
# 종합고 = 일반고인데 전문계 과정을 함께 운영하는 학교. 이름에는 '종합'이
# 안 들어간다(전국 2408곳 중 0곳) — 반드시 HS_GNRL_BUSNS_SC_NM 으로 가른다.
chk("일반고+전문계는 종합고",
    derive_category({"SCHUL_NM": "마장고등학교", "HS_SC_NM": "일반고",
                     "HS_GNRL_BUSNS_SC_NM": "전문계"}) == "종합고")
chk("일반고+일반계는 일반고 그대로",
    derive_category({"SCHUL_NM": "가운고등학교", "HS_SC_NM": "일반고",
                     "HS_GNRL_BUSNS_SC_NM": "일반계"}) == "일반고")
chk("특성화고+전문계는 특성화고 그대로",
    derive_category({"SCHUL_NM": "경기경영고등학교", "HS_SC_NM": "특성화고",
                     "HS_GNRL_BUSNS_SC_NM": "전문계"}) == "특성화고")
chk("특성화고+일반계도 특성화고 그대로",
    derive_category({"SCHUL_NM": "경기대명고등학교", "HS_SC_NM": "특성화고",
                     "HS_GNRL_BUSNS_SC_NM": "일반계"}) == "특성화고")
chk("마이스터고는 특목고+전문계라도 마이스터고",
    derive_category({"SCHUL_NM": "경기게임마이스터고등학교", "HS_SC_NM": "특목고",
                     "HS_GNRL_BUSNS_SC_NM": "전문계",
                     "SPCLY_PURPS_HS_ORD_NM": "산업수요맞춤형"}) == "마이스터고")
chk("이름에 종합이 들어가도 필드가 아니면 안 걸림",
    derive_category({"SCHUL_NM": "한국종합예술고등학교", "HS_SC_NM": "특목고",
                     "HS_GNRL_BUSNS_SC_NM": "일반계",
                     "SPCLY_PURPS_HS_ORD_NM": "예술계열"}) == "예술고")
chk("계열 표시 순서에 종합고", "종합고" in CATEGORY_ORDER)

# 다시 수집할 때 학교가 고친 연락처를 덮어쓰면 안 된다.
from app.import_neis import upsert as neis_upsert
db3 = SessionLocal()
row = {"ATPT_OFCDC_SC_CODE": "J10", "SD_SCHUL_CODE": "9999001",
       "SCHUL_NM": "연락처보존고등학교", "HS_SC_NM": "특성화고",
       "HS_GNRL_BUSNS_SC_NM": "전문계", "LCTN_SC_NM": "경기도",
       "ORG_RDNMA": "경기 수원시", "ORG_RDNDA": "1",
       "COEDU_SC_NM": "남여공학", "FOND_SC_NM": "공립",
       "ORG_TELNO": "031-111-1111", "HMPG_ADRES": "http://neis.example.kr"}
chk("신규 수집은 나이스 연락처를 넣는다",
    neis_upsert(db3, row, "sample", False) == "new")
db3.commit()
sc3 = db3.query(School).filter(School.name == "연락처보존고등학교").first()
chk("신규 학교 전화번호", sc3.phone == "031-111-1111", sc3.phone)

sc3.phone = "031-222-3333"          # 학교가 직접 고친 대표번호
sc3.website = "https://school-edited.kr"
db3.commit()
row["ORG_TELNO"] = "031-999-9999"
row["HMPG_ADRES"] = "http://neis-changed.example.kr"
neis_upsert(db3, row, "sample", False)
db3.commit(); db3.refresh(sc3)
chk("다시 수집해도 학교가 고친 전화번호 유지", sc3.phone == "031-222-3333", sc3.phone)
chk("홈페이지도 유지", sc3.website == "https://school-edited.kr", sc3.website)
chk("주소·계열은 계속 갱신됨", sc3.category == "특성화고" and "수원시" in sc3.address)

neis_upsert(db3, row, "sample", False, refresh_contact=True)
db3.commit(); db3.refresh(sc3)
chk("--refresh-contact 면 덮어쓴다", sc3.phone == "031-999-9999", sc3.phone)
db3.close()

db2 = SessionLocal()
db2.add(School(name="회귀종합고등학교", category="종합고", region="경기",
               address="양주시 1", coed=Coed.coed, is_visible=True, phone="031-0"))
db2.commit(); db2.close()
r = c.get("/api/schools?category=종합고&size=5").json()
chk("종합고로 검색됨", r["total"] == 1, str(r["total"]))
chk("계열 목록에 종합고", "종합고" in c.get("/api/meta").json()["categories"])

print("=== 시/군/구 목록은 검색과 같은 학교만 센다 ===")
# 목록에는 뜨는데 고르면 0건이면, 쓰는 사람에게는 검색이 고장 난 것으로 보인다.
from app.models import School as _School   # noqa: E402
_db = SessionLocal()
_hidden = _School(name="숨긴기장고", region="부산", category="특성화고",
                  address="부산광역시 기장군 정관읍 정관로 1", is_visible=False)
_db.add(_hidden); _db.commit(); _db.refresh(_hidden)
_hid_id = _hidden.id
_db.close()

_cities = [x["city"] for x in c.get("/api/sigungu", params={"region": "부산"}).json()]
chk("숨긴 학교의 시/군/구는 목록에 없다", "기장군" not in _cities, str(_cities))

_db = SessionLocal()
_db.get(_School, _hid_id).is_visible = True
_db.commit(); _db.close()
_cities = [x["city"] for x in c.get("/api/sigungu", params={"region": "부산"}).json()]
chk("노출하면 목록에 나온다", "기장군" in _cities, str(_cities))
# 그리고 목록에 있으면 실제로 검색도 돼야 한다.
_found = c.get("/api/schools", params={"region": "부산", "sigungu": "기장군"}).json()
chk("고르면 결과가 나온다", _found["total"] >= 1, str(_found["total"]))

_db = SessionLocal()
_db.delete(_db.get(_School, _hid_id)); _db.commit(); _db.close()

print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
