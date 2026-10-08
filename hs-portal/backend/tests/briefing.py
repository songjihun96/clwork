"""온라인 직업계고설명회 — 강사 프로필 검사.

프로필은 Setting 한 줄에 JSON 으로 들어간다. 그래서 확인할 것이 둘이다.
  1) 관리자만 고칠 수 있고, 누구나 볼 수 있는가
  2) **값이 깨져 있어도 화면이 안 죽는가** — 손으로 DB 를 만졌거나 예전
     형식이 남아 있을 때, 500 이 나면 설명회 페이지 전체가 열리지 않는다.
"""
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/briefing.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-partner-secret"
if os.path.exists("/tmp/briefing.db"):
    os.remove("/tmp/briefing.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient              # noqa: E402
from app.main import app                                # noqa: E402
from app.database import SessionLocal                   # noqa: E402
from app.models import Role, Setting, User              # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


def is_stream(url, vid):
    """회원에게 주는 잠긴 주소인가. 원본 /api/media 경로는 절대 안 나간다."""
    return (url or "").startswith(f"/api/member-video/stream/{vid}?t=")


db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"),
           name="관리자", role=Role.admin)
stu = User(email="s@t.kr", password_hash=hash_password("p1234567"),
           name="학생", role=Role.student)
db.add(adm); db.add(stu); db.commit()
db.refresh(adm); db.refresh(stu)
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
db.close()
c = TestClient(app)

CAREERS = [
    "국내 유일의 직업계고 전문언론 특성화고신문 강승구 대표",
    "現학교법인 기동학원 경기관광고등학교 홍보컨설팅 위원",
    "前서울시교육청 직업계고 홍보위원",
    "연200회 이상 연수 진행",
]

print("=== 1. 아직 아무것도 없을 때 ===")
r = c.get("/api/lecturer")
chk("로그인 없이도 200", r.status_code == 200, r.text)
p = r.json()
chk("빈 이름", p["name"] == "", str(p))
chk("빈 경력 목록", p["careers"] == [], str(p))
chk("필요한 칸이 다 있다",
    set(p) == {"name", "title", "photo", "careers", "links",
               "cta_label", "cta_url"}, str(sorted(p)))

print("=== 2. 저장은 관리자만 ===")
body = {"name": "강승구", "title": "특성화고신문 대표", "photo": "",
        "careers": CAREERS, "cta_label": "컨설팅 신청", "cta_url": "/consulting"}
chk("로그인 없으면 거부", c.put("/api/admin/lecturer", json=body).status_code in (401, 403))
chk("학생은 거부", c.put("/api/admin/lecturer", headers=SH, json=body).status_code == 403)
r = c.put("/api/admin/lecturer", headers=AH, json=body)
chk("관리자는 200", r.status_code == 200, r.text)
chk("저장 결과를 돌려준다", r.json()["name"] == "강승구", r.text)

print("=== 3. 저장한 값이 공개 화면에 나온다 ===")
p = c.get("/api/lecturer").json()
chk("이름", p["name"] == "강승구", str(p))
chk("경력 4줄", len(p["careers"]) == 4, str(len(p["careers"])))
chk("순서가 그대로", p["careers"][0] == CAREERS[0], p["careers"][0])
chk("한자도 그대로", "現" in p["careers"][1], p["careers"][1])
chk("버튼 정보", p["cta_label"] == "컨설팅 신청" and p["cta_url"] == "/consulting", str(p))

print("=== 4. 경력 줄 정리 ===")
r = c.put("/api/admin/lecturer", headers=AH,
          json={**body, "careers": ["  앞뒤 공백  ", "", "   ", "둘째 줄"]})
got = r.json()["careers"]
chk("빈 줄은 버린다", len(got) == 2, str(got))
chk("앞뒤 공백을 턴다", got[0] == "앞뒤 공백", repr(got[0]))

print("=== 5. 너무 많거나 너무 긴 것은 막는다 ===")
r = c.put("/api/admin/lecturer", headers=AH, json={**body, "careers": ["줄"] * 41})
chk("41줄은 거부", r.status_code == 400, r.text)
chk("몇 줄까지인지 알려준다", "40" in r.json().get("detail", ""), r.text)
r = c.put("/api/admin/lecturer", headers=AH, json={**body, "careers": ["가" * 201]})
chk("한 줄 201자는 거부", r.status_code == 400, r.text)
r = c.put("/api/admin/lecturer", headers=AH, json={**body, "careers": ["가" * 200]})
chk("200자는 통과", r.status_code == 200, r.text)

print("=== 6. 값이 깨져 있어도 화면은 열린다 ===")
# 여기서 500 이 나면 설명회 페이지가 통째로 안 열린다. 빈 프로필이 낫다.
db2 = SessionLocal()
row = db2.get(Setting, "lecturer_profile")
row.value = "이건 JSON 이 아니다"
db2.commit()
db2.close()
r = c.get("/api/lecturer")
chk("깨진 값이어도 200", r.status_code == 200, r.text)
chk("빈 프로필로 돌아온다", r.json()["name"] == "" and r.json()["careers"] == [], r.text)

db2 = SessionLocal()
db2.get(Setting, "lecturer_profile").value = json.dumps({"name": "이름만"})
db2.commit()
db2.close()
p = c.get("/api/lecturer").json()
chk("일부 칸만 있어도 나머지를 채운다", p["name"] == "이름만" and p["careers"] == [], str(p))

db2 = SessionLocal()
db2.get(Setting, "lecturer_profile").value = json.dumps({"careers": "목록이 아님"})
db2.commit()
db2.close()
chk("careers 가 목록이 아니면 빈 목록으로", c.get("/api/lecturer").json()["careers"] == [])

print("=== 7. 사진 올리기 ===")
png = (b"\x89PNG\r\n\x1a\n" + b"0" * 100)
r = c.post("/api/admin/lecturer/photo", headers=AH,
           files={"file": ("p.png", png, "image/png")})
chk("관리자 업로드 200", r.status_code == 200, r.text)
chk("접근 주소를 준다", r.json()["url"].startswith("/api/uploads/"), r.text)
chk("학생은 못 올린다",
    c.post("/api/admin/lecturer/photo", headers=SH,
           files={"file": ("p.png", png, "image/png")}).status_code == 403)
chk("이미지가 아니면 거부",
    c.post("/api/admin/lecturer/photo", headers=AH,
           files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400)

print("=== 8. 강의 구성 ===")
r = c.get("/api/briefing")
chk("로그인 없이 200", r.status_code == 200, r.text)
chk("아직 영상 없음", r.json()["video"] is None, r.text)
chk("챕터도 비어 있다", r.json()["chapters"] == [], r.text)
chk("강사 프로필도 함께 준다", "lecturer" in r.json(), str(sorted(r.json())))

from app.models import Video   # noqa: E402
d = SessionLocal()
lf = Video(kind="longform", title="설명회 강의", is_public=True,
           duration_sec=3600, file_path="/api/media/x.mp4")
sh = Video(kind="shorts", title="숏츠", is_public=True)
d.add(lf); d.add(sh); d.commit(); d.refresh(lf); d.refresh(sh)
LF, SHORTS_ID = lf.id, sh.id
d.close()

CH = [
    {"title": "직업계고의 정체성", "items": [], "start_sec": 0},
    {"title": "고졸취업의 진실 혹은 거짓",
     "items": ["고졸취업은 무시당하지 않아요", "고졸취업은 승진이 어렵지 않아요"],
     "start_sec": 764.5},
]
body = {"video_id": LF, "headline": "직업계고설명회", "intro": "차근차근 짚어 드립니다.",
        "chapters": CH}
chk("학생은 저장 못 함",
    c.put("/api/admin/briefing", headers=SH, json=body).status_code == 403)
r = c.put("/api/admin/briefing", headers=AH, json=body)
chk("관리자 저장 200", r.status_code == 200, r.text)

anon = c.get("/api/briefing").json()
chk("비회원에게는 영상 주소가 없다", anon["video"]["file_url"] == "", str(anon["video"]))
chk("비회원에게는 챕터 주소도 없다",
    all(ch["source"] is None for ch in anon["chapters"]), str(anon["chapters"]))
chk("잠긴 챕터라고 알려준다", all(ch["locked"] for ch in anon["chapters"]), str(anon["chapters"]))
chk("로그인이 필요하다고 알려준다", anon["login_required"] is True, str(anon))
chk("챕터 제목은 비회원도 본다", anon["chapters"][0]["title"] == "직업계고의 정체성")

pub = c.get("/api/briefing", headers=SH).json()
chk("회원은 로그인 필요 없음", pub["login_required"] is False, str(pub))
chk("영상이 연결된다", pub["video"]["id"] == LF, str(pub["video"]))
chk("회원에게는 잠긴 주소를 준다", is_stream(pub["video"]["file_url"], LF), str(pub["video"]))
chk("챕터 2개", len(pub["chapters"]) == 2, str(pub["chapters"]))
chk("하위 항목이 남는다", len(pub["chapters"][1]["items"]) == 2, str(pub["chapters"][1]))
chk("시작 초가 남는다", pub["chapters"][1]["start_sec"] == 764.5, str(pub["chapters"][1]))
chk("큰 제목", pub["headline"] == "직업계고설명회", str(pub))

print("=== 9. 비공개 영상은 주소를 안 내보낸다 ===")
# 주소가 나가면 그 주소로 그냥 볼 수 있다. 비공개의 뜻이 없어진다.
d = SessionLocal()
d.get(Video, LF).is_public = False
d.commit(); d.close()
pub = c.get("/api/briefing").json()
chk("주소가 비어 있다", pub["video"]["file_url"] == "", str(pub["video"]))
chk("잠겼다고 알려준다", pub["video"].get("locked") is True, str(pub["video"]))
d = SessionLocal()
d.get(Video, LF).is_public = True
d.commit(); d.close()

print("=== 10. 잘못된 구성은 막는다 ===")
chk("숏츠는 강의로 못 고른다",
    c.put("/api/admin/briefing", headers=AH,
          json={**body, "video_id": SHORTS_ID}).status_code == 400)
chk("없는 영상도 거부",
    c.put("/api/admin/briefing", headers=AH,
          json={**body, "video_id": 99999}).status_code == 400)
r = c.put("/api/admin/briefing", headers=AH,
          json={**body, "chapters": [{"title": "  ", "items": [], "start_sec": 0}]})
chk("빈 제목 챕터는 버린다", r.json()["chapters"] == [], r.text)
r = c.put("/api/admin/briefing", headers=AH,
          json={**body, "chapters": [{"title": "많음", "items": [], "start_sec": 0}] * 31})
chk("31개는 거부", r.status_code == 400, r.text)

print("=== 11. 구성이 깨져 있어도 페이지는 열린다 ===")
d = SessionLocal()
d.get(Setting, "briefing_config").value = "JSON 아님"
d.commit(); d.close()
r = c.get("/api/briefing")
chk("깨진 값이어도 200", r.status_code == 200, r.text)
chk("빈 구성으로 돌아온다", r.json()["chapters"] == [] and r.json()["video"] is None, r.text)

print("=== 12. 강사 소개 링크 ===")
r = c.put("/api/admin/lecturer", headers=AH, json={
    **body,
    "links": [
        {"label": "인스타그램", "url": "https://instagram.com/x"},
        {"label": "", "url": "https://sinmoon.net"},
        {"label": "주소 없음", "url": "  "},          # 버려져야 한다
        {"url": "https://youtube.com/x"},
        "문자열은 링크가 아님",
    ]})
links = r.json()["links"]
chk("주소 없는 줄은 버린다", len(links) == 3, str(links))
chk("이름이 있으면 그대로", links[0]["label"] == "인스타그램", str(links[0]))
chk("이름이 없으면 주소를 이름으로", links[1]["label"] == "https://sinmoon.net", str(links[1]))
chk("모양이 이상하면 건너뛴다", all(isinstance(x, dict) for x in links), str(links))
chk("공개 화면에도 나온다", len(c.get("/api/lecturer").json()["links"]) == 3)

print("=== 13. 강의(하위 항목)에 시각 ===")
CH2 = [{"title": "고졸취업의 진실 혹은 거짓", "start_sec": 1240, "items": [
    {"title": "무시당하지 않아요", "start_sec": 1240},
    {"title": "승진이 어렵지 않아요", "start_sec": 1420},
    {"title": "시각 없는 강의"},
]}]
r = c.put("/api/admin/briefing", headers=AH,
          json={"video_id": LF, "headline": "", "intro": "", "chapters": CH2})
items = r.json()["chapters"][0]["items"]
chk("강의 3개", len(items) == 3, str(items))
chk("강의 시각이 남는다", items[1]["start_sec"] == 1420, str(items[1]))
chk("시각 없는 강의는 None", items[2]["start_sec"] is None, str(items[2]))

print("=== 14. 예전 형식(문자열 강의)도 읽는다 ===")
# 이미 저장된 구성이 문자열이라, 못 읽으면 기존 챕터가 통째로 날아간다.
d = SessionLocal()
d.get(Setting, "briefing_config").value = json.dumps({
    "video_id": LF, "headline": "", "intro": "",
    "chapters": [{"title": "옛 챕터", "start_sec": 10,
                  "items": ["옛 강의 하나", "옛 강의 둘"]}]}, ensure_ascii=False)
d.commit(); d.close()
pub = c.get("/api/briefing").json()
old_items = pub["chapters"][0]["items"]
chk("문자열 강의를 살려 읽는다", len(old_items) == 2, str(old_items))
chk("제목이 그대로", old_items[0]["title"] == "옛 강의 하나", str(old_items[0]))
chk("시각은 없음으로", old_items[0]["start_sec"] is None, str(old_items[0]))

print("=== 15. 요약값 ===")
r = c.put("/api/admin/briefing", headers=AH,
          json={"video_id": LF, "headline": "", "intro": "", "chapters": CH2})
sm = c.get("/api/briefing").json()["summary"]
chk("챕터 수", sm["chapters"] == 1, str(sm))
chk("강의 수를 합산한다", sm["lessons"] == 3, str(sm))
chk("영상 길이도 준다", sm["duration_sec"] == 3600, str(sm))

print("=== 16. 챕터마다 다른 영상 ===")
d = SessionLocal()
v2 = Video(kind="longform", title="2강", is_public=True,
           duration_sec=600, file_path="/api/media/ch2.mp4")
v3 = Video(kind="longform", title="3강(비공개)", is_public=False,
           duration_sec=600, file_path="/api/media/ch3.mp4")
d.add(v2); d.add(v3); d.commit(); d.refresh(v2); d.refresh(v3)
V2, V3 = v2.id, v3.id
d.close()

body2 = {"video_id": LF, "headline": "", "intro": "", "chapters": [
    {"title": "기본 영상을 쓰는 챕터", "start_sec": 120},
    {"title": "제 영상을 가진 챕터", "video_id": V2, "items": [
        {"title": "앞부분"},
        {"title": "뒷부분", "start_sec": 300},
    ]},
    {"title": "비공개 영상 챕터", "video_id": V3},
]}
r = c.put("/api/admin/briefing", headers=AH, json=body2)
chk("저장 200", r.status_code == 200, r.text)

pub = c.get("/api/briefing", headers=SH).json()["chapters"]
chk("기본 영상 챕터는 기본 파일", is_stream(pub[0]["source"]["file_url"], LF),
    str(pub[0]["source"]))
chk("그 챕터는 적어 둔 초부터", pub[0]["source"]["start"] == 120, str(pub[0]["source"]))
chk("제 영상 챕터는 제 파일", is_stream(pub[1]["source"]["file_url"], V2),
    str(pub[1]["source"]))
chk("제 영상은 처음부터", pub[1]["source"]["start"] == 0, str(pub[1]["source"]))

lessons = pub[1]["items"]
chk("강의도 챕터 영상을 물려받는다",
    is_stream(lessons[0]["source"]["file_url"], V2), str(lessons[0]))
chk("시각 없는 강의는 0초", lessons[0]["source"]["start"] == 0, str(lessons[0]["source"]))
chk("시각을 적은 강의는 그 초", lessons[1]["source"]["start"] == 300, str(lessons[1]["source"]))

# 비공개 영상을 고른 챕터는 아예 못 틀게 한다. 기본 영상으로 슬쩍 바꿔치기하면
# 학생은 엉뚱한 영상을 보게 된다.
chk("비공개 영상 챕터는 재생 불가", pub[2]["source"] is None, str(pub[2]))

print("=== 17. 없는 영상은 저장 단계에서 막는다 ===")
r = c.put("/api/admin/briefing", headers=AH, json={
    "video_id": None, "headline": "", "intro": "",
    "chapters": [{"title": "엉뚱한 영상", "video_id": 99999}]})
chk("400 으로 거부", r.status_code == 400, r.text)
chk("어느 챕터인지 알려준다", "엉뚱한 영상" in r.json().get("detail", ""), r.text)

print("=== 18. 기본 영상 없이 챕터 영상만으로도 된다 ===")
r = c.put("/api/admin/briefing", headers=AH, json={
    "video_id": None, "headline": "", "intro": "",
    "chapters": [{"title": "1강", "video_id": V2}]})
chk("저장 200", r.status_code == 200, r.text)
pub = c.get("/api/briefing", headers=SH).json()
chk("기본 영상은 없음", pub["video"] is None, str(pub["video"]))
chk("챕터는 제 영상으로 재생된다",
    is_stream(pub["chapters"][0]["source"]["file_url"], V2),
    str(pub["chapters"][0]["source"]))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
