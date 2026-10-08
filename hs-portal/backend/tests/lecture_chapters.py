"""설명회 특강 카드와 영상 챕터 검사 (업.pdf 17번).

확인할 것:
  (1) 특강 카드 목록: 특강으로 올린 공개 롱폼만, 재생 주소 없이, 챕터 수와 함께
  (2) 숏츠 전체 공개 스위치가 꺼져 있어도 특강 상세는 열린다(회원만 재생)
  (3) 챕터: 통째 저장(추가·수정·삭제·순서), 하나씩 추가/고치기/지우기, 순서 바꾸기
  (4) 끝 시각이 비면 다음 챕터 시작 / 영상 끝으로 채워 준다
  (5) 틀린 시각(끝 ≤ 시작, 영상 길이 넘음)과 숏츠에 챕터는 막는다
  (6) 관리자만 챕터를 바꾼다
  (7) 특강 파일은 /api/media 로 못 받는다(회원 전용). 영상을 지우면 챕터도 지워진다
실행:  cd backend && python tests/lecture_chapters.py
"""
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "udj_lecture_test.db")
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
from app.models import Role, User, Video, VideoChapter  # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"), name="관리자", role=Role.admin)
stu = User(email="s@t.kr", password_hash=hash_password("p1234567"), name="학생", role=Role.student)
db.add_all([adm, stu])
db.commit()
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
SH = {"Authorization": f"Bearer {create_access_token(stu)}"}
os.makedirs(videos_mod.MEDIA_DIR, exist_ok=True)
NAME = "_lc_test_lecture.mp4"
with open(os.path.join(videos_mod.MEDIA_DIR, NAME), "wb") as f:
    f.write(b"\x00" * 4096)
lec = Video(kind="longform", title="직업계고 A to Z", description="40분 특강", is_public=True,
            duration_sec=2400, file_path=f"/api/media/{NAME}", category="입학")
plain = Video(kind="longform", title="그냥 롱폼", is_public=True, duration_sec=600)
hidden = Video(kind="longform", title="비공개 특강", is_public=False, duration_sec=600)
sh = Video(kind="shorts", title="숏츠", is_public=True, duration_sec=30)
db.add_all([lec, plain, hidden, sh])
db.commit()
LEC, PLAIN, HIDDEN, SHORTS = lec.id, plain.id, hidden.id, sh.id
db.close()
c = TestClient(app)

try:
    print("=== 1. 특강으로 올리기 ===")
    chk("처음엔 카드 없음", c.get("/api/lectures").json() == [])
    r = c.patch(f"/api/admin/videos/{LEC}", json={"is_lecture": True}, headers=AH)
    chk("관리자가 올림", r.status_code == 200 and r.json()["is_lecture"] is True, r.text)
    c.patch(f"/api/admin/videos/{HIDDEN}", json={"is_lecture": True}, headers=AH)
    chk("학생은 못 올림",
        c.patch(f"/api/admin/videos/{PLAIN}", json={"is_lecture": True}, headers=SH).status_code == 403)
    r = c.patch(f"/api/admin/videos/{SHORTS}", json={"is_lecture": True}, headers=AH)
    chk("숏츠는 특강이 될 수 없다", r.status_code == 400, r.text)
    cards = c.get("/api/lectures").json()
    chk("공개 특강만 카드로", [x["id"] for x in cards] == [LEC], str(cards))
    chk("카드에 재생 주소가 없다", "file_url" not in cards[0], str(cards[0]))
    chk("카드에 분류·길이·회원 전용",
        cards[0]["category"] == "입학" and cards[0]["duration_sec"] == 2400 and cards[0]["members_only"])

    print("=== 2. 공개 스위치가 꺼져 있어도 특강 상세는 열린다 ===")
    chk("숏츠 공개 스위치 꺼짐", c.get("/api/videos/visibility").json()["public"] is False)
    chk("그냥 롱폼은 404", c.get(f"/api/videos/{PLAIN}").status_code == 404)
    d = c.get(f"/api/videos/{LEC}").json()
    chk("특강 상세는 열림", d.get("id") == LEC, str(d)[:200])
    chk("비회원: 재생 주소 없음", d["file_url"] == "" and d.get("login_required") is True, str(d)[:200])
    d = c.get(f"/api/videos/{LEC}", headers=SH).json()
    chk("회원: 잠긴 주소", d["file_url"].startswith(f"/api/member-video/stream/{LEC}?t="), d["file_url"])
    chk("회원: 받아진다", c.get(d["file_url"]).status_code == 200)
    chk("원본 주소는 막힘", c.get(f"/api/media/{NAME}").status_code == 403)
    chk("조회수 올리기도 열림", c.post(f"/api/videos/{LEC}/view").status_code == 200)

    print("=== 3. 챕터 통째 저장 ===")
    body = {"chapters": [
        {"title": "1부", "start_sec": 0, "end_sec": 1200},
        {"title": "2부", "start_sec": 1200},
    ]}
    chk("학생은 못 바꿈",
        c.put(f"/api/admin/videos/{LEC}/chapters", json=body, headers=SH).status_code == 403)
    r = c.put(f"/api/admin/videos/{LEC}/chapters", json=body, headers=AH)
    chk("저장", r.status_code == 200 and len(r.json()) == 2, r.text)
    ch = r.json()
    chk("순서", [x["title"] for x in ch] == ["1부", "2부"])
    chk("끝이 빈 마지막 챕터는 영상 끝까지", ch[1]["end_sec"] is None and ch[1]["effective_end_sec"] == 2400,
        str(ch[1]))
    d = c.get(f"/api/videos/{LEC}").json()
    chk("상세에 챕터가 온다(비회원도 목록은 봄)", [x["title"] for x in d["chapters"]] == ["1부", "2부"])
    chk("카드에 챕터 수", c.get("/api/lectures").json()[0]["chapter_count"] == 2)

    body = {"chapters": [
        {"title": "들어가며", "start_sec": 0},
        {"title": "1부", "start_sec": 60},
        {"title": "2부", "start_sec": 1200, "end_sec": 2400},
    ]}
    ch = c.put(f"/api/admin/videos/{LEC}/chapters", json=body, headers=AH).json()
    chk("끝이 빈 챕터는 다음 시작까지", ch[0]["effective_end_sec"] == 60 and ch[1]["effective_end_sec"] == 1200,
        str(ch))

    print("=== 4. 하나씩 고치기 · 순서 ===")
    ch = c.post(f"/api/admin/videos/{LEC}/chapters", json={"title": "질문과 답", "start_sec": 2300},
                headers=AH).json()
    chk("추가", ch[-1]["title"] == "질문과 답", str(ch))
    qid = ch[-1]["id"]
    ch = c.patch(f"/api/admin/video-chapters/{qid}", json={"title": "Q&A", "start_sec": 2280},
                 headers=AH).json()
    chk("고치기", ch[-1]["title"] == "Q&A" and ch[-1]["start_sec"] == 2280, str(ch[-1]))
    ids = [x["id"] for x in ch]
    new_order = [ids[-1]] + ids[:-1]
    ch = c.put(f"/api/admin/videos/{LEC}/chapters/order", json={"ids": new_order}, headers=AH).json()
    chk("순서 바꾸기", [x["id"] for x in ch] == new_order, str([x["id"] for x in ch]))
    r = c.put(f"/api/admin/videos/{LEC}/chapters/order", json={"ids": new_order[:2]}, headers=AH)
    chk("빠뜨리면 400", r.status_code == 400)
    ch = c.delete(f"/api/admin/video-chapters/{qid}", headers=AH).json()
    chk("지우기", qid not in [x["id"] for x in ch] and len(ch) == 3)
    chk("학생은 못 지움", c.delete(f"/api/admin/video-chapters/{ch[0]['id']}", headers=SH).status_code == 403)

    print("=== 5. 틀린 시각은 막는다 ===")
    r = c.put(f"/api/admin/videos/{LEC}/chapters",
              json={"chapters": [{"title": "거꾸로", "start_sec": 100, "end_sec": 50}]}, headers=AH)
    chk("끝 ≤ 시작", r.status_code == 400 and "거꾸로" in r.json()["detail"], r.text)
    r = c.put(f"/api/admin/videos/{LEC}/chapters",
              json={"chapters": [{"title": "넘침", "start_sec": 2500}]}, headers=AH)
    chk("영상 길이 넘음", r.status_code == 400, r.text)
    r = c.put(f"/api/admin/videos/{LEC}/chapters",
              json={"chapters": [{"title": "  ", "start_sec": 0}]}, headers=AH)
    chk("빈 제목", r.status_code in (400, 422), r.text)
    chk("막힌 뒤 기존 챕터는 그대로", len(c.get(f"/api/admin/videos/{LEC}/chapters", headers=AH).json()) == 3)
    r = c.put(f"/api/admin/videos/{SHORTS}/chapters",
              json={"chapters": [{"title": "x", "start_sec": 0}]}, headers=AH)
    chk("숏츠에는 챕터 없음", r.status_code == 400)

    print("=== 6. 관리자 상세 ===")
    d = c.get(f"/api/admin/videos/{LEC}", headers=AH).json()
    chk("관리자 상세에 챕터·특강 여부", len(d["chapters"]) == 3 and d["is_lecture"] is True)

    print("=== 7. 특강에서 내리면 다시 열린다 · 지우면 챕터도 ===")
    c.patch(f"/api/admin/videos/{LEC}", json={"is_lecture": False}, headers=AH)
    chk("카드에서 빠짐", c.get("/api/lectures").json() == [])
    chk("원본 주소가 다시 열림", c.get(f"/api/media/{NAME}").status_code == 200)
    chk("영상 지우기", c.delete(f"/api/admin/videos/{LEC}", headers=AH).status_code == 200)
    s = SessionLocal()
    chk("챕터도 지워짐", s.query(VideoChapter).filter_by(video_id=LEC).count() == 0)
    s.close()
finally:
    try:
        os.remove(os.path.join(videos_mod.MEDIA_DIR, NAME))
    except OSError:
        pass

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
