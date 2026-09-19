"""돈 낸 사람만 보는 영상(합격생 영상) 검사.

파는 물건이라 확인할 것이 셋이다.
  1) **안 산 사람에게 주소가 안 나가는가** — 화면에서 가리는 건 가리는 게
     아니다. 응답에 stream_url 자체가 없어야 한다.
  2) **주소를 알아도 못 받는가** — 티켓 없이, 남의 티켓으로, 취소된 뒤에.
  3) 산 사람은 실제로 받는가. 앞으로 감기(Range)까지 되는가.

그리고 신청 자체가 로그인 없이는 안 들어가야 한다. 계정이 없으면 입금을
확인해 놓고도 누구에게 열어 줄지 알 수가 없다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/paid_video.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-partner-secret"
if os.path.exists("/tmp/paid_video.db"):
    os.remove("/tmp/paid_video.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient                 # noqa: E402
from app.main import app                                   # noqa: E402
from app.database import SessionLocal                      # noqa: E402
from app.models import Role, ServiceApplication, User, Video   # noqa: E402
from app.auth import create_access_token, hash_password    # noqa: E402
from app import applications as ap                         # noqa: E402
from app import paidvideo as pv                            # noqa: E402
from app import videos as vmod                             # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


# ---- 사람과 영상 준비 -------------------------------------------------
db = SessionLocal()
adm = User(email="a@t.kr", password_hash=hash_password("p1234567"),
           name="관리자", role=Role.admin)
buyer = User(email="b@t.kr", password_hash=hash_password("p1234567"),
             name="김구매", phone="010-1234-5678", role=Role.student)
other = User(email="o@t.kr", password_hash=hash_password("p1234567"),
             name="안샀음", role=Role.student)
db.add_all([adm, buyer, other]); db.commit()
for u in (adm, buyer, other):
    db.refresh(u)
AH = {"Authorization": f"Bearer {create_access_token(adm)}"}
BH = {"Authorization": f"Bearer {create_access_token(buyer)}"}
OH = {"Authorization": f"Bearer {create_access_token(other)}"}
BUYER_ID = buyer.id

# 영상 하나. 파일은 진짜로 만든다 — 바이트가 나가는지까지 봐야 한다.
os.makedirs(vmod.MEDIA_DIR, exist_ok=True)
NAME = "test_paid_video.bin"
BLOB = bytes(range(256)) * 40          # 10,240 바이트
with open(os.path.join(vmod.MEDIA_DIR, NAME), "wb") as f:
    f.write(BLOB)
vid = Video(kind="longform", title="합격 이후", file_path=f"/api/media/{NAME}",
            is_public=False)
free = Video(kind="longform", title="공짜 특강", file_path="/api/media/none.mp4",
             is_public=True)
db.add_all([vid, free]); db.commit()
db.refresh(vid); db.refresh(free)
VID, FREE_ID = vid.id, free.id
db.close()

c = TestClient(app)
ap._RECENT.clear()

print("=== 1. 관리자가 구성을 짠다 ===")
r = c.put("/api/admin/graduate-video", headers=AH, json={
    "headline": "합격 이후를 준비하는 영상", "intro": "세 챕터입니다.",
    "chapters": [{"title": "자기소개서", "video_id": VID},
                 {"title": "포트폴리오", "video_id": None}]})
chk("저장 200", r.status_code == 200, r.text)
chk("챕터 2개", len(r.json()["chapters"]) == 2, r.text)
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "  ", "video_id": VID}]})
chk("빈 제목은 막는다", r.status_code == 400, r.text)
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "없는 영상", "video_id": 99999}]})
chk("없는 영상은 막는다", r.status_code == 400, r.text)
r = c.get("/api/admin/graduate-video")
chk("관리 조회는 관리자만", r.status_code in (401, 403), r.text)
# 앞의 실패가 구성을 망가뜨리지 않았는지 — 실패했으면 원래 것이 남아야 한다
r = c.get("/api/admin/graduate-video", headers=AH)
chk("실패해도 구성이 남아 있다", len(r.json()["chapters"]) == 2, r.text)

print("=== 2. 안 산 사람에게는 주소가 없다 ===")
r = c.get("/api/graduate-video")
chk("비로그인 200", r.status_code == 200, r.text)
d = r.json()
chk("챕터 제목은 보인다", d["chapters"][0]["title"] == "자기소개서", r.text)
chk("주소는 없다", d["chapters"][0]["source"] is None, r.text)
chk("owned=False", d["owned"] is False, r.text)
chk("워터마크도 없다", d["watermark"] == "", r.text)
r = c.get("/api/graduate-video", headers=OH)
chk("로그인만 해도 주소는 없다", r.json()["chapters"][0]["source"] is None, r.text)

print("=== 3. 신청에는 로그인이 필요하다 ===")
BASE = {"kind": "graduate_video", "name": "김구매", "phone": "010-1234-5678",
        "found_path": "소개", "applicant": "본인"}
r = c.post("/api/applications", json=BASE)
chk("비로그인 신청은 401", r.status_code == 401, r.text)
r = c.get("/api/applications/info", params={"kind": "graduate_video"})
chk("화면이 미리 알 수 있다", r.json()["login_required"] is True, r.text)
r = c.get("/api/applications/info", params={"kind": "counseling"})
chk("다른 폼은 그대로 무로그인", r.json()["login_required"] is False, r.text)

ap._RECENT.clear()
r = c.post("/api/applications", headers=BH, json=BASE)
chk("로그인하면 접수 200", r.status_code == 200, r.text)
APP_ID = r.json()["id"]
db = SessionLocal()
row = db.get(ServiceApplication, APP_ID)
chk("신청이 계정에 묶인다", row.user_id == BUYER_ID, str(row.user_id))
db.close()

print("=== 4. 입금 확인 전에는 아직 못 본다 ===")
r = c.get("/api/graduate-video", headers=BH)
d = r.json()
chk("접수 상태가 보인다", d["application"]["status"] == "received", r.text)
chk("아직 주소는 없다", d["chapters"][0]["source"] is None, r.text)

print("=== 5. 입금을 확인하면 열린다 ===")
r = c.patch(f"/api/admin/applications/{APP_ID}", headers=AH, json={"status": "paid"})
chk("상태 변경 200", r.status_code == 200, r.text)
r = c.get("/api/graduate-video", headers=BH)
d = r.json()
chk("owned=True", d["owned"] is True, r.text)
URL = d["chapters"][0]["source"]["file_url"]
chk("주소가 생겼다", bool(URL), r.text)
chk("워터마크에 이름", "김구매" in d["watermark"], d["watermark"])
chk("워터마크에 번호 끝자리", "5678" in d["watermark"], d["watermark"])
chk("번호 전체는 안 나간다", "010-1234-5678" not in d["watermark"], d["watermark"])
chk("영상 없는 챕터는 주소가 없다", d["chapters"][1]["source"] is None, r.text)

print("=== 6. 실제로 받아진다 ===")
r = c.get(URL)
chk("티켓으로 200", r.status_code == 200, r.text[:200])
chk("내용이 맞다", r.content == BLOB, str(len(r.content)))
r = c.get(URL, headers={"Range": "bytes=100-199"})
chk("앞으로 감기(Range) 206", r.status_code == 206, r.text[:200])
chk("구간이 맞다", r.content == BLOB[100:200], str(len(r.content)))

print("=== 7. 주소를 알아도 티켓이 없으면 못 받는다 ===")
bare = URL.split("?")[0]
ticket = URL.split("t=")[1]
chk("티켓 없이 403", c.get(bare).status_code == 403)
chk("엉뚱한 티켓 403", c.get(bare + "?t=abc.def.ghi").status_code == 403)
chk("로그인 토큰으로는 안 된다",
    c.get(bare + "?t=" + OH["Authorization"].split()[1]).status_code == 403)
chk("다른 영상에 같은 티켓을 못 쓴다",
    c.get(f"/api/graduate-video/stream/{FREE_ID}?t={ticket}").status_code in (403, 404))
chk("구성에 없는 영상은 404",
    c.get(f"/api/graduate-video/stream/{FREE_ID}?t={pv.make_ticket(BUYER_ID, FREE_ID)}"
          ).status_code == 404)

print("=== 8. 취소하면 그 자리에서 막힌다 ===")
# 티켓은 세 시간을 산다. 그 사이 상태가 바뀌면 티켓이 남아 있어도 막혀야 한다.
r = c.patch(f"/api/admin/applications/{APP_ID}", headers=AH, json={"status": "cancelled"})
chk("취소 200", r.status_code == 200, r.text)
chk("살아 있던 티켓도 403", c.get(URL).status_code == 403)
r = c.get("/api/graduate-video", headers=BH)
chk("목록에서도 주소가 사라진다", r.json()["chapters"][0]["source"] is None, r.text)
chk("취소 상태가 보인다", r.json()["application"]["status"] == "cancelled", r.text)

print("=== 9. 관리자는 늘 볼 수 있다 ===")
r = c.get("/api/graduate-video", headers=AH)
chk("관리자 owned", r.json()["owned"] is True, r.text)
chk("관리자도 재생된다", c.get(r.json()["chapters"][0]["source"]["file_url"]).status_code == 200)

print("=== 10. 완료 처리해도 계속 볼 수 있다 ===")
c.patch(f"/api/admin/applications/{APP_ID}", headers=AH, json={"status": "done"})
r = c.get("/api/graduate-video", headers=BH)
chk("done 도 시청 가능", r.json()["owned"] is True, r.text)
chk("다시 받아진다", c.get(r.json()["chapters"][0]["source"]["file_url"]).status_code == 200)

print("=== 11. 정적 폴더 옆문 ===")
# 잠근 길을 아무리 잘 만들어도 /api/media 가 열려 있으면 소용이 없다.
FREE_NAME = "test_free_video.bin"
with open(os.path.join(vmod.MEDIA_DIR, FREE_NAME), "wb") as f:
    f.write(b"free")
chk("무료 영상은 그대로 나간다", c.get(f"/api/media/{FREE_NAME}").status_code == 200)
chk("파는 영상은 막힌다", c.get(f"/api/media/{NAME}").status_code == 403)
# 예전 StaticFiles 는 HEAD 를 받아 줬다. 재생기·프록시가 본편 전에 HEAD 로
# 길이를 물어보는 경우가 있어 그대로 받아 줘야 한다.
chk("무료 영상에 HEAD 가 된다", c.head(f"/api/media/{FREE_NAME}").status_code == 200)
chk("파는 영상은 HEAD 도 막힌다", c.head(f"/api/media/{NAME}").status_code == 403)
chk("폴더를 거슬러 올라갈 수 없다",
    c.get("/api/media/..%2F..%2Fapp%2Fmain.py").status_code == 404)
chk("없는 파일은 404", c.get("/api/media/nope.mp4").status_code == 404)

# 구성에서 빼면 다시 열려야 한다 — 안 그러면 한 번 붙였던 영상이 영영 막힌다.
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "이제 영상 없음", "video_id": None}]})
chk("구성에서 빼면 200", r.status_code == 200, r.text)
chk("빼면 정적 폴더로도 나간다", c.get(f"/api/media/{NAME}").status_code == 200)
os.remove(os.path.join(vmod.MEDIA_DIR, FREE_NAME))
os.remove(os.path.join(vmod.MEDIA_DIR, NAME))

print("=== 12. 특강과 같은 영상을 못 쓴다 ===")
# 한 파일을 무료로도 주고 팔 수는 없다. 그냥 두면 파는 쪽 잠금이 특강을
# 403 으로 깨뜨리는데, 아무 말 없이 깨지는 것이 제일 나쁘다.
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "유료", "video_id": VID, "items": []}]})
chk("파는 쪽 구성 되돌리기", r.status_code == 200, r.text)
db5 = SessionLocal(); db5.get(Video, FREE_ID).is_public = True; db5.commit(); db5.close()
r = c.put("/api/admin/briefing", headers=AH, json={
    "video_id": None, "headline": "", "intro": "", "cover": "",
    "chapters": [{"title": "무료", "video_id": VID, "start_sec": 0, "items": []}]})
chk("특강이 파는 영상을 못 가져간다", r.status_code == 400, r.text[:120])
r = c.put("/api/admin/briefing", headers=AH, json={
    "video_id": None, "headline": "", "intro": "", "cover": "",
    "chapters": [{"title": "무료", "video_id": FREE_ID, "start_sec": 0, "items": []}]})
chk("겹치지 않으면 저장된다", r.status_code == 200, r.text[:120])
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "유료", "video_id": FREE_ID, "items": []}]})
chk("파는 쪽도 특강 영상을 못 가져간다", r.status_code == 400, r.text[:120])
r = c.put("/api/admin/graduate-video", headers=AH,
          json={"chapters": [{"title": "유료", "video_id": VID, "items": []}]})
chk("원래대로는 저장된다", r.status_code == 200, r.text[:120])

print("=== 13. 같은 계정이 두 번 신청 ===")
ap._RECENT.clear()
r = c.post("/api/applications", headers=BH, json=BASE)
chk("이미 있는 계정은 막힌다", r.status_code == 409, r.text[:120])
db6 = SessionLocal()
n = db6.query(ServiceApplication).filter(
    ServiceApplication.user_id == BUYER_ID,
    ServiceApplication.kind == "graduate_video").count()
db6.close()
chk("신청이 하나만 남는다", n == 1, "%d건" % n)

print("=== 14. 관리자가 열리는 계정을 본다 ===")
r = c.get("/api/admin/applications", headers=AH, params={"kind": "graduate_video"})
acc = r.json()["items"][0].get("account")
chk("계정이 함께 내려온다", bool(acc), r.text[:160])
chk("계정 이메일이 맞다", acc and acc["email"] == "b@t.kr", str(acc))
r = c.get("/api/admin/applications", headers=AH, params={"kind": "counseling"})
chk("로그인 없는 신청은 계정이 없다",
    all(x.get("account") is None for x in r.json()["items"]), r.text[:120])

print("=== 15. 다 보고 나서 남기는 후기 ===")
d = c.get("/api/graduate-video", headers=BH).json()
chk("처음엔 안 남긴 상태", d["reviewed"] is False, str(d.get("reviewed")))
ap._RECENT.clear()
REV = {"kind": "graduate_video_review", "name": "(후기)", "phone": "-",
       "message": "자소서 부분이 도움됐습니다.", "extra": {"별점": "4점"}}
r = c.post("/api/applications", json=REV)
chk("비로그인은 후기도 못 남긴다", r.status_code == 401, r.text[:80])
ap._RECENT.clear()
r = c.post("/api/applications", headers=BH, json=REV)
chk("산 사람은 남길 수 있다", r.status_code == 200, r.text[:120])
d = c.get("/api/graduate-video", headers=BH).json()
chk("남긴 뒤에는 reviewed", d["reviewed"] is True, str(d.get("reviewed")))
ap._RECENT.clear()
r = c.post("/api/applications", headers=BH, json=REV)
chk("두 번은 못 남긴다", r.status_code == 409, r.text[:120])
chk("후기에 맞는 안내가 나온다", "후기" in r.json().get("detail", ""), r.text[:120])
r = c.get("/api/admin/applications", headers=AH, params={"kind": "graduate_video_review"})
items = r.json()["items"]
chk("관리자 목록에 보인다", len(items) == 1, str(len(items)))
chk("별점이 담긴다", items and items[0]["extra"].get("별점") == "4점", str(items[:1]))
chk("누가 남겼는지 계정이 보인다",
    items and (items[0].get("account") or {}).get("email") == "b@t.kr", str(items[:1]))

print("=== 16. 엑셀 내려받기 ===")
r = c.get("/api/admin/applications.csv", headers=AH)
chk("관리자는 받는다", r.status_code == 200, r.text[:80])
body = r.text
chk("엑셀이 한글을 안 깨게 BOM 이 있다", body[:1] == "﻿", repr(body[:4]))
chk("열리는 계정 칸이 있다", "열리는 계정" in body, body[:200])
chk("계정이 실제로 적힌다", "b@t.kr" in body, body[:400])
chk("로그인 없이는 못 받는다", c.get("/api/admin/applications.csv").status_code in (401, 403))
r = c.get("/api/admin/applications.csv", headers=BH)
chk("일반 계정도 못 받는다", r.status_code == 403, str(r.status_code))

print()
print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
