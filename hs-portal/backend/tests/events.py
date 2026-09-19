"""학교 일정(입시 일정·학교 설명회) 검사.

확인할 것: (1) 시간·장소·신청 링크·수정 기능이 실제로 동작한다,
(2) 신청 링크는 http/https 만 허용한다(XSS 방어), (3) 다른 학교 소유자는
못 고친다, (4) 학생 화면(상세)·전체 목록·즐겨찾기 화면에 새 필드가 나온다.
"""
import os, sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/events.db"; os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-partner-secret"

if os.path.exists("/tmp/events.db"):
    os.remove("/tmp/events.db")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import hash_password, create_access_token
from datetime import date, timedelta

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
sc1 = School(name="설명회고등학교", category="특성화고", region="경기", address="수원시",
             coed=Coed.coed, plan=Plan.premium, is_visible=True, phone="031-000-0000")
sc2 = School(name="다른고등학교", category="특성화고", region="경기", address="용인시",
             coed=Coed.coed, plan=Plan.premium, is_visible=True, phone="031-000-0001")
db.add(sc1); db.add(sc2); db.commit(); db.refresh(sc1); db.refresh(sc2)
SID1, SID2 = sc1.id, sc2.id

sch1 = User(email="sc1@t.kr", password_hash=hash_password("p1234567"), name="설명회고 담당자",
            role=Role.school, school_id=SID1)
sch2 = User(email="sc2@t.kr", password_hash=hash_password("p1234567"), name="다른고 담당자",
            role=Role.school, school_id=SID2)
stu = User(email="stu@t.kr", password_hash=hash_password("p1234567"), name="학생",
           role=Role.student, school_id=SID1)
db.add(sch1); db.add(sch2); db.add(stu)
db.commit(); [db.refresh(u) for u in (sch1, sch2, stu)]
CH1 = {"Authorization": f"Bearer {create_access_token(sch1)}"}
CH2 = {"Authorization": f"Bearer {create_access_token(sch2)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
db.close()
c = TestClient(app)

D1 = (date.today() + timedelta(days=10)).isoformat()
D2 = (date.today() + timedelta(days=24)).isoformat()
D3 = (date.today() + timedelta(days=38)).isoformat()

print("=== 1. 여러 날짜에 걸친 학교 설명회 — 같은 이름으로 각각 등록 ===")
for d in (D1, D2, D3):
    r = c.post("/api/school-admin/events", json={
        "kind": "briefing", "title": "2026학년도 입학 설명회",
        "start_date": d, "start_time": "14:00", "end_time": "16:00",
        "location": "본관 3층 강당", "registration_url": "https://forms.example.com/apply",
        "description": "1부: 학교 소개\n2부: 학과 안내\n3부: 질의응답",
    }, headers=CH1)
    chk(f"{d} 설명회 등록", r.status_code == 200, str(r.json())[:150])

r = c.get("/api/school-admin/events", headers=CH1)
items = r.json()
briefings = [e for e in items if e["kind"] == "briefing"]
chk("등록된 설명회 3건", len(briefings) == 3, str(len(briefings)))
chk("시간·장소·신청링크가 그대로 저장됨",
    briefings[0]["start_time"] == "14:00" and briefings[0]["end_time"] == "16:00"
    and briefings[0]["location"] == "본관 3층 강당"
    and briefings[0]["registration_url"] == "https://forms.example.com/apply")
chk("설명 줄바꿈이 그대로 저장됨", "\n" in briefings[0]["description"])

print("=== 1b. 한 번에 여러 날짜 등록(배치) ===")
r = c.post("/api/school-admin/events/batch", json={
    "kind": "briefing", "title": "여름방학 학교 탐방",
    "location": "운동장", "registration_url": "https://forms.example.com/summer",
    "description": "체험 프로그램 안내",
    "dates": [
        {"start_date": D1, "start_time": "10:00", "end_time": "12:00"},
        {"start_date": D2, "start_time": "10:00", "end_time": "12:00"},
    ],
}, headers=CH1)
chk("배치 등록 200", r.status_code == 200, str(r.json())[:150])
chk("배치로 2건 생성됨", len(r.json()) == 2, str(len(r.json())))
chk("두 건 모두 공통 필드 공유", all(e["location"] == "운동장" for e in r.json()))
chk("각자 날짜는 다름", r.json()[0]["start_date"] != r.json()[1]["start_date"])

r = c.post("/api/school-admin/events/batch", json={
    "kind": "briefing", "title": "빈 배치", "dates": [],
}, headers=CH1)
chk("날짜 0개면 거부", r.status_code == 422, str(r.status_code))

r = c.get("/api/school-admin/events", headers=CH1)
chk("배치분 포함 총 5건(설명회 3 + 배치 2)",
    len([e for e in r.json() if e["kind"] == "briefing"]) == 5)
for e in r.json():
    if e["title"] == "여름방학 학교 탐방":
        c.delete(f"/api/school-admin/events/{e['id']}", headers=CH1)

print("=== 2. 신청 링크는 http/https 만 허용(XSS 방어) ===")
r = c.post("/api/school-admin/events", json={
    "kind": "admission", "title": "원서 접수", "start_date": D1,
    "registration_url": "javascript:alert(1)",
}, headers=CH1)
chk("javascript: 스킴 거부", r.status_code == 422, str(r.status_code))

print("=== 3. 시간 형식 검증 ===")
r = c.post("/api/school-admin/events", json={
    "kind": "admission", "title": "원서 접수", "start_date": D1, "start_time": "25:99",
}, headers=CH1)
chk("잘못된 시간 형식 거부", r.status_code == 422, str(r.status_code))

print("=== 4. 수정 기능 ===")
event_id = briefings[0]["id"]
r = c.put(f"/api/school-admin/events/{event_id}", json={"location": "본관 4층 대강당"}, headers=CH1)
chk("수정 성공", r.status_code == 200, str(r.json())[:150])
chk("장소만 바뀌고 나머지는 그대로", r.json()["location"] == "본관 4층 대강당"
    and r.json()["start_time"] == "14:00" and r.json()["title"] == "2026학년도 입학 설명회")

print("=== 5. 다른 학교는 남의 일정 못 고치고 못 지운다 ===")
r = c.put(f"/api/school-admin/events/{event_id}", json={"location": "해킹"}, headers=CH2)
chk("다른 학교는 수정 시도 시 404", r.status_code == 404)
r = c.delete(f"/api/school-admin/events/{event_id}", headers=CH2)
chk("다른 학교는 삭제 시도 시 404", r.status_code == 404)

print("=== 6. 학생 화면(학교 상세)에 새 필드가 그대로 나온다 ===")
r = c.get(f"/api/schools/{SID1}", headers=SH)
detail_briefings = [e for e in r.json()["events"] if e["kind"] == "briefing"]
chk("학교 상세에 설명회 3건", len(detail_briefings) == 3, str(len(detail_briefings)))
chk("학교 상세에도 장소·시간·신청링크 포함",
    any(e["location"] == "본관 4층 대강당" for e in detail_briefings)
    and all(e["registration_url"] == "https://forms.example.com/apply" for e in detail_briefings))

print("=== 7. 전체 일정 모아보기(/api/events)에도 새 필드가 나온다 ===")
r = c.get("/api/events", params={"kind": "briefing"})
chk("전체 목록 200", r.status_code == 200)
mine = [e for e in r.json() if e["school_id"] == SID1]
chk("전체 목록에 시간·장소 포함", len(mine) == 3 and all(e.get("start_time") == "14:00" for e in mine))

print("=== 8. 즐겨찾기 캘린더에도 새 필드가 나온다 ===")
c.post("/api/favorites", json={"school_id": SID1}, headers=SH)
r = c.get("/api/favorites/calendar", headers=SH)
chk("즐겨찾기 캘린더 200", r.status_code == 200)
chk("즐겨찾기 캘린더에 시간 포함",
    any(e.get("start_time") == "14:00" for e in r.json() if e["school_id"] == SID1))

print("=== 9. 삭제 ===")
r = c.delete(f"/api/school-admin/events/{event_id}", headers=CH1)
chk("본인 학교는 삭제 가능", r.status_code == 200)
r = c.get("/api/school-admin/events", headers=CH1)
chk("삭제 후 2건 남음", len([e for e in r.json() if e["kind"] == "briefing"]) == 2)

print("=== 10. 날짜마다 장소를 따로 적을 수 있다 ===")
# 같은 설명회라도 회차별로 장소가 다를 수 있다. 공통 장소는 '안 적은 칸'의
# 기본값일 뿐이고, 칸에 적은 장소가 그 날짜에 그대로 붙어야 한다.
r = c.post("/api/school-admin/events/batch", headers=CH1, json={
    "kind": "briefing", "title": "회차별 장소 설명회",
    "location": "공통 장소",
    "dates": [
        {"start_date": str(date.today() + timedelta(days=20)), "location": "본관 3층 강당"},
        {"start_date": str(date.today() + timedelta(days=21)), "location": "실습동 2층"},
        {"start_date": str(date.today() + timedelta(days=22))},
    ],
})
chk("날짜별 장소로 일괄 등록 200", r.status_code == 200, r.text)
made = r.json() if r.status_code == 200 else []
chk("1회차는 본관 3층 강당", len(made) == 3 and made[0]["location"] == "본관 3층 강당",
    str([e.get("location") for e in made]))
chk("2회차는 실습동 2층", len(made) == 3 and made[1]["location"] == "실습동 2층")
chk("장소를 안 적은 칸은 공통 장소", len(made) == 3 and made[2]["location"] == "공통 장소")

r = c.put(f"/api/school-admin/events/{made[0]['id']}", headers=CH1, json={"location": "체육관"})
chk("한 회차 장소만 수정 가능", r.status_code == 200 and r.json()["location"] == "체육관", r.text)
r = c.get("/api/school-admin/events", headers=CH1)
rest = [e for e in r.json() if e["id"] == made[1]["id"]]
chk("다른 회차 장소는 그대로", rest and rest[0]["location"] == "실습동 2층")

print("=== 11. 학교 소개 영상(유튜브)은 유튜브 주소만 받는다 ===")
r = c.put("/api/school-admin/profile", headers=CH1, json={
    "youtube_urls": "https://www.youtube.com/watch?v=dQw4w9WgXcQ" + chr(10) + "https://youtu.be/aBcDeFgHiJk",
})
chk("유튜브 주소 2개 저장 200", r.status_code == 200, r.text)
r = c.get(f"/api/schools/{SID1}")
vids = r.json().get("youtube_videos", [])
chk("상세에 영상 2개", len(vids) == 2, str(vids))
chk("embed 주소가 nocookie",
    bool(vids) and vids[0]["embed_url"] == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
r = c.put("/api/school-admin/profile", headers=CH1, json={"youtube_urls": "https://vimeo.com/12345"})
chk("유튜브가 아니면 422", r.status_code == 422, r.text)
r = c.put("/api/school-admin/profile", headers=CH1, json={
    "youtube_urls": chr(10).join([
        "https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/aBcDeFgHiJk",
        "https://youtu.be/9bZkp7q19f0", "https://youtu.be/kJQP7kiw5Fk"])})
chk("4개까지는 통과", r.status_code == 200, r.text)
r = c.get(f"/api/schools/{SID1}")
chk("상세에 영상 4개", len(r.json().get("youtube_videos", [])) == 4)
r = c.put("/api/school-admin/profile", headers=CH1, json={
    "youtube_urls": chr(10).join(["https://youtu.be/dQw4w9WgXcQ"] * 5)})
chk("5개는 422", r.status_code == 422, r.text)
r = c.get(f"/api/schools/{SID1}")
chk("거절된 뒤에도 앞서 넣은 영상 4개 그대로", len(r.json().get("youtube_videos", [])) == 4)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
