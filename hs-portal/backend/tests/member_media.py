"""회원 전용 영상(설명회·학교 인터뷰)과 방문자 수 검사.

확인할 것:
  (1) 설명회·인터뷰에 붙은 파일은 /api/media 로 못 받는다(옆문)
  (2) 로그인한 회원은 티켓 주소로 받는다. 티켓이 없거나 다른 영상 것이면 못 받는다
  (3) 관리자 영상 관리 화면의 미리보기 주소는 관리자 티켓으로 열린다
  (4) 인터뷰 목록은 누구나 보고, 재생 주소는 회원에게만 나간다
  (5) 파는 영상(합격생 영상)의 파일을 인터뷰에 못 붙인다
  (6) 롱폼 보기(/api/videos/{id})도 같은 규칙을 따른다
  (7) 방문자는 하루 한 번만 세고, 봇은 안 센다. 누적 시작값이 더해진다
실행:  cd backend && python tests/member_media.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "udj_member_media_test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
os.environ["SECRET_KEY"] = "x"
os.environ.setdefault("PARTNER_SECRET", "test-partner-secret")
if os.path.exists(DB):
    os.remove(DB)
sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app import videos as videos_mod  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Coed, Plan, Role, School, Setting, User, Video  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537.36"}

db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"), name="관리자", role=Role.admin)
stu = User(email="s@t.kr", password_hash=hash_password("p1234567"), name="학생", role=Role.student)
sch = School(name="인터뷰고등학교", category="특성화고", region="경기", address="수원",
             coed=Coed.coed, plan=Plan.free, is_visible=True, phone="031-1")
db.add_all([adm, stu, sch])
db.commit()
for o in (adm, stu, sch):
    db.refresh(o)
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
SCHOOL_ID = sch.id

os.makedirs(videos_mod.MEDIA_DIR, exist_ok=True)
NAMES = {k: f"_mm_test_{k}.mp4" for k in ("brief", "iv", "free", "paid")}
for k, n in NAMES.items():
    with open(os.path.join(videos_mod.MEDIA_DIR, n), "wb") as f:
        f.write(b"\x00" * 2048 + k.encode())
vids = {}
for k, n in NAMES.items():
    v = Video(kind="longform", title=f"{k} 영상", is_public=(k != "paid"),
              duration_sec=60, file_path=f"/api/media/{n}")
    db.add(v)
    db.commit()
    db.refresh(v)
    vids[k] = v.id
db.close()
c = TestClient(app)

try:
    print("=== 1. 설명회에 붙이면 옆문이 닫힌다 ===")
    chk("붙이기 전에는 그냥 받아진다", c.get(f"/api/media/{NAMES['brief']}").status_code == 200)
    r = c.put("/api/admin/briefing", headers=AH, json={
        "video_id": vids["brief"], "headline": "", "intro": "",
        "chapters": [{"title": "1강", "start_sec": 0}]})
    chk("설명회 저장", r.status_code == 200, r.text)
    chk("붙인 뒤에는 403", c.get(f"/api/media/{NAMES['brief']}").status_code == 403)
    chk("HEAD 도 403", c.head(f"/api/media/{NAMES['brief']}").status_code == 403)
    chk("상관없는 무료 영상은 그대로", c.get(f"/api/media/{NAMES['free']}").status_code == 200)

    print("=== 2. 회원은 티켓 주소로 받는다 ===")
    anon = c.get("/api/briefing").json()
    chk("비회원은 주소 없음", anon["chapters"][0]["source"] is None and anon["login_required"])
    url = c.get("/api/briefing", headers=SH).json()["chapters"][0]["source"]["file_url"]
    r = c.get(url)
    chk("회원 티켓으로 200", r.status_code == 200, str(r.status_code))
    chk("내용이 맞다", r.content.endswith(b"brief"))
    chk("앞으로 감기(Range)가 된다",
        c.get(url, headers={"Range": "bytes=0-9"}).status_code == 206)
    chk("티켓 없으면 403",
        c.get(f"/api/member-video/stream/{vids['brief']}").status_code == 403)
    chk("엉터리 티켓 403",
        c.get(f"/api/member-video/stream/{vids['brief']}?t=abc").status_code == 403)
    tok = url.split("t=")[1]
    chk("다른 영상 번호에 티켓을 돌려 쓰면 403",
        c.get(f"/api/member-video/stream/{vids['free']}?t={tok}").status_code == 403)
    from app import membervideo  # noqa: E402
    free_tok = membervideo.make_ticket(1, vids["free"])
    chk("회원 영상이 아닌 것은 이 길로 404",
        c.get(f"/api/member-video/stream/{vids['free']}?t={free_tok}").status_code == 404)
    chk("로그인 토큰은 티켓으로 못 쓴다",
        c.get(f"/api/member-video/stream/{vids['brief']}?t={SH['Authorization'][7:]}").status_code == 403)

    print("=== 3. 관리자 미리보기 ===")
    rows = c.get("/api/admin/videos", headers=AH).json()
    row = next(x for x in rows if x["id"] == vids["brief"])
    chk("관리자 주소에는 티켓이 붙는다", "?t=" in row["file_url"], row["file_url"])
    chk("관리자 주소로 받아진다", c.get(row["file_url"]).status_code == 200)
    student_like = membervideo._encode({"sub": "2", "purpose": membervideo.ADMIN_PURPOSE,
                                        "exp": 9999999999})
    chk("학생 계정의 관리자 티켓은 안 먹는다",
        c.get(f"/api/media/{NAMES['brief']}?t={student_like}").status_code == 403)
    one = c.get(f"/api/admin/videos/{vids['brief']}", headers=AH).json()
    chk("상세에도 티켓", "?t=" in one["file_url"], one["file_url"])

    print("=== 4. 학교 인터뷰 ===")
    body = {"title": "우리 학교를 소개합니다", "summary": "교장 선생님과 재학생 인터뷰",
            "speakers": "교장 · 재학생 2명", "school_id": SCHOOL_ID,
            "video_id": vids["iv"], "is_published": False}
    chk("학생은 못 만든다", c.post("/api/admin/interviews", headers=SH, json=body).status_code == 403)
    r = c.post("/api/admin/interviews", headers=AH, json=body)
    chk("관리자가 만든다", r.status_code == 200, r.text)
    IID = r.json()["id"]
    chk("게시 전에도 파일은 잠긴다", c.get(f"/api/media/{NAMES['iv']}").status_code == 403)
    chk("게시 전에는 목록에 없다", c.get("/api/interviews").json()["items"] == [])
    chk("게시 전에는 상세 404", c.get(f"/api/interviews/{IID}", headers=SH).status_code == 404)

    r = c.put(f"/api/admin/interviews/{IID}", headers=AH, json={**body, "is_published": True})
    chk("게시", r.status_code == 200, r.text)
    lst = c.get("/api/interviews").json()
    chk("비회원도 목록은 본다", len(lst["items"]) == 1, str(lst))
    chk("목록에 학교 이름", lst["items"][0]["school"]["name"] == "인터뷰고등학교", str(lst))
    chk("목록에는 재생 주소가 없다", "source" not in lst["items"][0], str(lst["items"][0]))
    chk("학교별로 거른다",
        len(c.get("/api/interviews", params={"school_id": SCHOOL_ID}).json()["items"]) == 1
        and c.get("/api/interviews", params={"school_id": 99999}).json()["items"] == [])

    d = c.get(f"/api/interviews/{IID}").json()
    chk("비회원 상세: 로그인 필요", d["login_required"] is True and d["source"] is None, str(d))
    chk("비회원 상세: 영상은 있다고 알려 준다", d["has_video"] is True)
    chk("비회원은 조회수에 안 든다", d["view_count"] == 0, str(d["view_count"]))
    d = c.get(f"/api/interviews/{IID}", headers=SH).json()
    chk("회원 상세: 잠긴 주소", (d["source"] or {}).get("file_url", "").startswith(
        f"/api/member-video/stream/{vids['iv']}?t="), str(d))
    chk("회원 상세: 받아진다", c.get(d["source"]["file_url"]).status_code == 200)
    chk("회원이 보면 조회수 1", d["view_count"] == 1, str(d["view_count"]))

    print("=== 5. 잘못 넣은 것은 막는다 ===")
    r = c.post("/api/admin/interviews", headers=AH, json={**body, "video_id": None,
                                                           "is_published": True})
    chk("영상 없이 게시 못 함", r.status_code == 400, r.text)
    r = c.post("/api/admin/interviews", headers=AH, json={**body, "school_id": None,
                                                           "school_name": ""})
    chk("학교 없이 못 만듦", r.status_code == 400, r.text)
    r = c.post("/api/admin/interviews", headers=AH, json={**body, "school_id": None,
                                                           "school_name": "포털에 없는 분교"})
    chk("목록에 없는 학교는 이름만으로 된다", r.status_code == 200, r.text)
    c.delete(f"/api/admin/interviews/{r.json()['id']}", headers=AH)

    r = c.put("/api/admin/graduate-video", headers=AH, json={
        "headline": "", "intro": "", "cover": "",
        "chapters": [{"title": "유료", "video_id": vids["paid"], "items": []}]})
    chk("합격생 영상 저장", r.status_code == 200, r.text)
    r = c.post("/api/admin/interviews", headers=AH, json={**body, "video_id": vids["paid"]})
    chk("파는 영상 파일은 인터뷰에 못 붙인다", r.status_code == 400, r.text)
    paid_tok = membervideo.make_ticket(2, vids["paid"])
    chk("회원 티켓으로 파는 영상을 못 받는다",
        c.get(f"/api/member-video/stream/{vids['paid']}?t={paid_tok}").status_code == 404)

    print("=== 6. 롱폼 보기도 같은 규칙 ===")
    c.put("/api/admin/videos-visibility", headers=AH, json={"public": True})
    v = c.get(f"/api/videos/{vids['brief']}").json()
    chk("비회원: 주소 없음 + 로그인 필요",
        v["file_url"] == "" and v.get("login_required") is True, str(v))
    v = c.get(f"/api/videos/{vids['brief']}", headers=SH).json()
    chk("회원: 잠긴 주소", v["file_url"].startswith("/api/member-video/stream/"), v["file_url"])
    v = c.get(f"/api/videos/{vids['free']}").json()
    chk("무료 영상은 예전 그대로", v["file_url"] == f"/api/media/{NAMES['free']}", v["file_url"])
    lst = c.get("/api/videos", params={"kind": "longform"}).json()
    brief_row = next(x for x in lst if x["id"] == vids["brief"])
    chk("목록에서도 비회원에게 주소 없음", brief_row["file_url"] == "", str(brief_row))

    print("=== 7. 지우면 잠금이 풀린다 ===")
    chk("삭제", c.delete(f"/api/admin/interviews/{IID}", headers=AH).status_code == 200)
    chk("인터뷰에서 뺀 파일은 다시 열린다", c.get(f"/api/media/{NAMES['iv']}").status_code == 200)

    print("=== 8. 방문자 수 ===")
    r = c.post("/api/visit", json={"visitor_id": "aaa"}, headers=BROWSER)
    chk("첫 방문", r.status_code == 200 and r.json()["today"] == 1, r.text)
    r = c.post("/api/visit", json={"visitor_id": "aaa"}, headers=BROWSER)
    chk("같은 사람은 한 번만", r.json()["today"] == 1, r.text)
    r = c.post("/api/visit", json={"visitor_id": "bbb"}, headers=BROWSER)
    chk("다른 사람은 더한다(같은 IP 라도)", r.json()["today"] == 2, r.text)
    r = c.post("/api/visit", json={"visitor_id": "ccc"},
               headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"})
    chk("봇은 안 센다", r.json()["today"] == 2, r.text)
    r = c.post("/api/visit", json={"visitor_id": ""}, headers=BROWSER)
    chk("값 없는 요청은 안 센다", r.json()["today"] == 2, r.text)
    chk("누적도 2", c.get("/api/visit-stats").json()["total"] == 2)
    chk("시작값은 관리자만",
        c.put("/api/admin/visit-stats", headers=SH, json={"base": 1000}).status_code == 403)
    r = c.put("/api/admin/visit-stats", headers=AH, json={"base": 1000})
    chk("시작값 저장", r.status_code == 200, r.text)
    chk("누적에 시작값이 더해진다", c.get("/api/visit-stats").json()["total"] == 1002,
        c.get("/api/visit-stats").text)
    chk("오늘은 그대로", c.get("/api/visit-stats").json()["today"] == 2)

    from app import visits  # noqa: E402
    old = visits.MAX_NEW_PER_IP
    visits.MAX_NEW_PER_IP = 3
    for i in range(10):
        c.post("/api/visit", json={"visitor_id": f"spam{i}"}, headers=BROWSER)
    chk("한 IP 가 값을 바꿔 가며 부풀리지 못한다",
        c.get("/api/visit-stats").json()["today"] == 3, c.get("/api/visit-stats").text)
    visits.MAX_NEW_PER_IP = old
finally:
    for n in NAMES.values():
        try:
            os.remove(os.path.join(videos_mod.MEDIA_DIR, n))
        except OSError:
            pass

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
