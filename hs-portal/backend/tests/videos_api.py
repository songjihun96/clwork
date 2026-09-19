"""롱폼·숏츠 API 전체 흐름 검사.

**대본 없이 소리 지문만으로 돈다.** 예전에는 대본을 넣어 글자를 맞추는
방식이라 영상 파일 없이도 매칭을 검사할 수 있었는데, 지금은 소리가 근거다.
그래서 지문을 **직접 만들어 DB 에 심고** 매칭을 돌린다 — ffmpeg 로 영상에서
소리를 뽑는 부분만 건너뛰고, 그 뒤의 판단은 실제 경로 그대로 지난다.

numpy 가 없으면 지문을 만들 수 없으므로 매칭 부분은 건너뛴다(나머지는 돈다).

BackgroundTasks 는 TestClient 가 응답을 돌려주기 전에 동기로 실행해 준다.
그래서 분석 요청 뒤 바로 결과를 확인할 수 있다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/videos_api.db"
os.environ["SECRET_KEY"] = "x"
os.environ["PARTNER_SECRET"] = "test-partner-secret"
if os.path.exists("/tmp/videos_api.db"):
    os.remove("/tmp/videos_api.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                            # noqa: E402
from app.database import SessionLocal               # noqa: E402
from app.models import Role, User, VideoFingerprint  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app import fingerprint as fp_mod               # noqa: E402

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


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

# fp_mod.available() 은 ffmpeg 까지 있어야 참이다(파일에서 소리를 뽑아야 하므로).
# 여기서는 지문을 직접 심으므로 numpy 만 있으면 된다.
try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


# ---------------------------------------------------------------- 지문 심기
def _speechlike(sec, seed):
    """말소리 비슷한 신호. 기본 주파수가 흔들리는 배음 + 사이사이 쉼."""
    import numpy as np
    r = np.random.default_rng(seed)
    n = int(fp_mod.SAMPLE_RATE * sec)
    t = np.arange(n) / fp_mod.SAMPLE_RATE
    sig = np.zeros(n, dtype="float32")
    for k in range(1, 6):
        f = 110 + 60 * np.sin(2 * np.pi * 0.7 * t + r.uniform(0, 6))
        sig += (0.6 / k) * np.sin(2 * np.pi * f * k * t + r.uniform(0, 6))
    env = (np.sin(2 * np.pi * 1.7 * t + r.uniform(0, 6)) > -0.3).astype("float32")
    return (sig * env + 0.01 * r.standard_normal(n)).astype("float32")


def _fp_of(sig):
    spec = fp_mod._spectrogram(sig)
    h, t = fp_mod._hashes(fp_mod._peaks(spec))
    return fp_mod.Fingerprint(hashes=h, times=t, frames=int(spec.shape[0]))


def plant(video_id, sig):
    """영상에 소리 지문을 심는다(ffmpeg 없이 매칭 경로를 그대로 태우기 위해)."""
    f = _fp_of(sig)
    d = SessionLocal()
    row = d.query(VideoFingerprint).filter(
        VideoFingerprint.video_id == video_id).first()
    if not row:
        row = VideoFingerprint(video_id=video_id)
        d.add(row)
    row.data = f.to_bytes()
    row.hash_count = f.count
    row.status = "completed"
    row.error = ""
    d.commit()
    d.close()


def make(kind, title, **kw):
    r = c.post("/api/admin/videos", headers=AH, json={"kind": kind, "title": title, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def set_duration(video_id, sec):
    """길이는 보통 ffmpeg 가 재 준다. 파일이 없으니 직접 적어 둔다."""
    from app.models import Video
    d = SessionLocal()
    d.get(Video, video_id).duration_sec = sec
    d.commit()
    d.close()


print("=== 1. 롱폼 등록 ===")
r = c.post("/api/admin/videos", headers=AH,
           json={"kind": "longform", "title": "취업 특강", "description": "1시간", "is_public": True})
chk("롱폼 생성 200", r.status_code == 200, r.text)
LF = r.json()["id"]
chk("kind 가 longform", r.json()["kind"] == "longform")
chk("숏츠 목록은 빈 배열", r.json()["shorts"] == [])
chk("지문은 아직 없음", r.json()["fingerprint"]["status"] == "none", str(r.json()["fingerprint"]))
chk("대본 칸은 이제 없다", "transcript" not in r.json(), str(sorted(r.json())))
set_duration(LF, 3600)

chk("학생은 못 만든다",
    c.post("/api/admin/videos", headers=SH,
           json={"kind": "longform", "title": "x"}).status_code == 403)
chk("로그인 없이도 못 만든다",
    c.post("/api/admin/videos", json={"kind": "longform", "title": "x"}).status_code in (401, 403))

print("=== 2. 숏츠 등록과 연결 ===")
S1 = make("shorts", "면접에서 중요한 것", longform_id=LF, is_public=True)
set_duration(S1, 30)
d = c.get(f"/api/admin/videos/{S1}", headers=AH).json()
chk("숏츠가 롱폼에 붙는다", d["match"]["longform_id"] == LF, str(d.get("match")))
chk("처음 상태는 pending", d["match"]["status"] == "pending", str(d["match"]))
chk("롱폼 제목도 함께 준다", d["match"]["longform_title"] == "취업 특강", str(d["match"]))
chk("없는 롱폼에는 못 붙인다",
    c.post("/api/admin/videos", headers=AH,
           json={"kind": "shorts", "title": "x", "longform_id": 99999}).status_code == 400)

lf = c.get(f"/api/admin/videos/{LF}", headers=AH).json()
chk("롱폼 상세에 숏츠가 보인다", len(lf["shorts"]) == 1, str(lf["shorts"]))

print("=== 3. 지문이 없으면 분석은 실패로 남는다 ===")
# 여기서 그냥 "실패"만 남기면 관리자가 무엇을 해야 할지 알 수 없다.
r = c.post(f"/api/admin/videos/{S1}/match", headers=AH)
chk("분석 요청 200", r.status_code == 200, r.text)
m = c.get(f"/api/admin/videos/{S1}", headers=AH).json()["match"]
chk("상태 failed", m["status"] == "failed", str(m))
chk("어느 쪽 지문이 없는지 알려준다", "롱폼" in (m["note"] or ""), m["note"])
chk("롱폼이 아니면 분석 거부",
    c.post(f"/api/admin/videos/{LF}/match", headers=AH).status_code == 400)

if not HAVE_NUMPY:
    print("  (numpy 없음 — 매칭 검사 건너뜀)")
else:
    print("=== 4. 소리로 원본 구간을 찾는다 ===")
    LONG = _speechlike(240, 1)
    TRUE = 137.0
    SEG = LONG[int(TRUE * fp_mod.SAMPLE_RATE):int((TRUE + 18) * fp_mod.SAMPLE_RATE)].copy()
    set_duration(LF, 240)
    set_duration(S1, 18)
    plant(LF, LONG)
    plant(S1, SEG)

    c.post(f"/api/admin/videos/{S1}/match", headers=AH)
    m = c.get(f"/api/admin/videos/{S1}", headers=AH).json()["match"]
    chk("찾음(completed)", m["status"] == "completed", str(m))
    chk("시작 시각이 맞는다", abs(m["source_start_time"] - TRUE) < 0.5,
        str(m["source_start_time"]))
    chk("끝 시각은 숏츠 길이만큼",
        abs(m["source_end_time"] - (m["source_start_time"] + 18)) < 0.5, str(m))
    chk("방식은 소리 지문", m["method"] == "audio", m["method"])
    chk("일치도가 있다", m["audio_score"] is not None, str(m))
    chk("대본 점수는 없다", m["text_score"] is None and m["sequence_score"] is None, str(m))
    chk("신뢰도가 높다", (m["confidence"] or 0) >= 0.9, str(m["confidence"]))

    print("=== 5. 관계없는 소리는 확정하지 않는다 ===")
    ODD = make("shorts", "엉뚱한 숏츠", longform_id=LF)
    set_duration(ODD, 18)
    plant(ODD, _speechlike(18, 555))
    c.post(f"/api/admin/videos/{ODD}/match", headers=AH)
    m = c.get(f"/api/admin/videos/{ODD}", headers=AH).json()["match"]
    chk("확정하지 않는다", m["status"] != "completed", str(m))
    chk("왜 못 찾았는지 알려준다", "소리" in (m["note"] or ""), m["note"])

    print("=== 6. 사람이 고친 구간은 재분석이 덮지 않는다 ===")
    mid = c.get(f"/api/admin/videos/{S1}", headers=AH).json()["match"]["id"]
    r = c.put(f"/api/admin/matches/{mid}", headers=AH,
              json={"source_start_time": 12.5, "source_end_time": 40.0, "note": "관리자 수정"})
    chk("수정 200", r.status_code == 200, r.text)
    chk("값이 반영됨", r.json()["source_start_time"] == 12.5, r.text)
    chk("수정 표시가 붙는다", r.json()["manually_modified"] is True)
    c.post(f"/api/admin/videos/{S1}/match", headers=AH)
    m = c.get(f"/api/admin/videos/{S1}", headers=AH).json()["match"]
    chk("재분석해도 시각 그대로", m["source_start_time"] == 12.5, str(m))
    chk("끝 시각도 그대로", m["source_end_time"] == 40.0, str(m))
    chk("시작이 끝보다 뒤면 거부",
        c.put(f"/api/admin/matches/{mid}", headers=AH,
              json={"source_start_time": 50, "source_end_time": 10}).status_code == 400)

    print("=== 7. 확정 ===")
    r = c.post(f"/api/admin/matches/{mid}/confirm", headers=AH)
    chk("확정 200", r.status_code == 200, r.text)
    chk("상태 confirmed", r.json()["status"] == "confirmed", r.text)
    chk("확인 표시", r.json()["manually_verified"] is True)

    print("=== 8. 한 번에 분석 ===")
    r = c.post(f"/api/admin/videos/{LF}/match-all", headers=AH)
    chk("일괄 분석 200", r.status_code == 200, r.text)
    chk("확정된 것은 건너뛴다", r.json()["queued"] >= 1, r.text)
    p = c.get(f"/api/admin/videos/{LF}/match-progress", headers=AH)
    chk("진행 상황 200", p.status_code == 200, p.text)
    chk("숏츠 수를 알려준다", p.json()["total"] == 2, p.text)

print("=== 9. 학생 화면 — 공개 전에는 안 보인다 ===")
chk("기본은 감춤", c.get("/api/videos").status_code == 404)
chk("주소를 직접 쳐도 안 열림", c.get(f"/api/videos/{S1}").status_code == 404)
chk("관리자는 그대로 본다", c.get(f"/api/admin/videos/{S1}", headers=AH).status_code == 200)
chk("학생은 관리자 목록 못 봄",
    c.get("/api/admin/videos", headers=SH).status_code == 403)

r = c.put("/api/admin/videos-visibility", headers=AH, json={"public": True})
chk("공개 전환 200", r.status_code == 200, r.text)
chk("학생은 못 바꾼다",
    c.put("/api/admin/videos-visibility", headers=SH, json={"public": True}).status_code == 403)
chk("공개 여부 조회", c.get("/api/videos/visibility").json()["public"] is True)

r = c.get("/api/videos")
chk("이제 목록 200", r.status_code == 200, r.text)
titles = [v["title"] for v in r.json()]
chk("공개 영상만 나온다", "엉뚱한 숏츠" not in titles, str(titles))

print("=== 10. 학생에게 원본 구간은 확정된 것만 ===")
d = c.get(f"/api/videos/{S1}")
chk("숏츠 상세 200", d.status_code == 200, d.text)
body = d.json()
chk("대본은 안 내려간다", "transcript" not in body, str(sorted(body)))
chk("분석 내부값도 안 내려간다", "match" not in body, str(sorted(body)))
if HAVE_NUMPY:
    chk("확정됐으니 원본 구간이 온다", body["source"] is not None, str(body))
    chk("시작 초를 준다", body["source"]["start"] == 12.5, str(body["source"]))
    chk("롱폼 제목도 준다", body["source"]["longform_title"] == "취업 특강", str(body["source"]))

r = c.post(f"/api/videos/{S1}/view")
chk("조회수 200", r.status_code == 200, r.text)
chk("조회수가 오른다",
    c.get(f"/api/admin/videos/{S1}", headers=AH).json()["view_count"] >= 1)

print("=== 11. 비공개 롱폼으로는 넘어갈 수 없다 ===")
# 눌러도 못 여는 영상으로 학생을 보내지 않는다.
c.patch(f"/api/admin/videos/{LF}", headers=AH, json={"is_public": False})
chk("롱폼이 비공개면 구간을 안 준다", c.get(f"/api/videos/{S1}").json()["source"] is None)
c.patch(f"/api/admin/videos/{LF}", headers=AH, json={"is_public": True})
if HAVE_NUMPY:
    chk("다시 공개하면 나온다", c.get(f"/api/videos/{S1}").json()["source"] is not None)

print("=== 12. 목록이 연결 정보를 함께 준다 ===")
lst = c.get("/api/admin/videos", headers=AH, params={"kind": "shorts"}).json()
row = next(x for x in lst if x["id"] == S1)
chk("붙은 롱폼 번호", row["link"]["longform_id"] == LF, str(row.get("link")))
chk("롱폼 이름", row["link"]["longform_title"] == "취업 특강", str(row.get("link")))
lf_rows = c.get("/api/admin/videos", headers=AH, params={"kind": "longform"}).json()
chk("롱폼 줄에는 link 를 안 붙인다", "link" not in lf_rows[0], str(sorted(lf_rows[0])))

print("=== 13. 연결 끊기와 다시 붙이기 ===")
r = c.patch(f"/api/admin/videos/{S1}", headers=AH, json={"longform_id": None})
chk("null 이면 연결이 끊긴다", r.json()["match"] is None, r.text)
r = c.patch(f"/api/admin/videos/{S1}", headers=AH, json={"title": "이름만 바꿈"})
chk("longform_id 를 안 보내면 연결은 안 건드린다", r.json()["match"] is None, r.text)
r = c.patch(f"/api/admin/videos/{S1}", headers=AH, json={"longform_id": LF})
chk("다시 붙는다", r.json()["match"]["longform_id"] == LF, r.text)
chk("붙일 때 구간은 초기화", r.json()["match"]["status"] == "pending", r.text)

print("=== 14. 삭제 ===")
ORP = make("shorts", "미아가 될 숏츠", longform_id=LF)
r = c.delete(f"/api/admin/videos/{LF}", headers=AH)
chk("롱폼 삭제 200", r.status_code == 200, r.text)
chk("숏츠는 남긴다", c.get(f"/api/admin/videos/{ORP}", headers=AH).status_code == 200)
lst = c.get("/api/admin/videos", headers=AH, params={"kind": "shorts"}).json()
row = next((x for x in lst if x["id"] == ORP), None)
chk("연결 끊긴 숏츠가 목록에 나온다", row is not None)
chk("연결이 없다고 알려 준다", row is not None and not row.get("link"), str(row))
chk("연결 끊긴 숏츠를 지울 수 있다",
    c.delete(f"/api/admin/videos/{ORP}", headers=AH).status_code == 200)
chk("정말 사라졌다", c.get(f"/api/admin/videos/{ORP}", headers=AH).status_code == 404)

L2 = make("longform", "함께 지울 롱폼")
S2 = make("shorts", "함께 지울 숏츠", longform_id=L2)
r = c.delete(f"/api/admin/videos/{L2}", headers=AH, params={"with_shorts": "true"})
chk("함께 삭제 200", r.status_code == 200, r.text)
chk("둘 다 지웠다고 알려 준다", r.json().get("deleted") == 2, r.text)
chk("딸린 숏츠도 사라짐", c.get(f"/api/admin/videos/{S2}", headers=AH).status_code == 404)

print("=== 15. 자동 확정 기준 ===")
r = c.get("/api/admin/videos-thresholds", headers=AH)
chk("기준 조회 200", r.status_code == 200, r.text)
chk("기본 확정선 0.95", abs(r.json()["confirm"] - 0.95) < 1e-6, r.text)
chk("학생은 못 본다", c.get("/api/admin/videos-thresholds", headers=SH).status_code == 403)
chk("범위를 벗어나면 거부",
    c.put("/api/admin/videos-thresholds", headers=AH, json={"confirm": 1.5}).status_code == 422)
r = c.put("/api/admin/videos-thresholds", headers=AH, json={"confirm": 0.7})
chk("기준 저장 200", r.status_code == 200, r.text)
chk("저장된 값이 다시 조회됨",
    abs(c.get("/api/admin/videos-thresholds", headers=AH).json()["confirm"] - 0.7) < 1e-6)

print("=== 16. 환경 상태 ===")
r = c.get("/api/admin/stt-status", headers=AH)
chk("상태 조회 200", r.status_code == 200, r.text)
chk("지문 가능 여부를 준다", isinstance(r.json()["fingerprint"], bool), r.text)
chk("ffmpeg 여부를 준다", isinstance(r.json()["ffmpeg"], bool), r.text)
chk("크기 한도를 준다", r.json()["max_video_mb"] > 0, r.text)
chk("전사 정보는 사라졌다", "provider" not in r.json(), str(sorted(r.json())))
chk("학생은 못 본다", c.get("/api/admin/stt-status", headers=SH).status_code == 403)

print("=== 17. 다시 감추기 ===")
chk("감추기 200",
    c.put("/api/admin/videos-visibility", headers=AH, json={"public": False}).status_code == 200)
chk("감추면 학생은 다시 404", c.get("/api/videos").status_code == 404)
chk("감춰도 관리자는 그대로",
    c.get("/api/admin/videos", headers=AH).status_code == 200)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
