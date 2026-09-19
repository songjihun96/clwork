"""학생 포트폴리오 기능 검사.

지시서 64번 섹션에 나열된 시나리오를 그대로 확인한다 — 학생 간 격리,
교사 개인 노트 격리, AI 작업 중복 방지, 순서 변경 저장, 이미지 업로드,
공유는 보기 전용인지. AI는 실제로 부르지 않고 흉내 낸다.
"""
import os, sys, json, time
os.environ["DATABASE_URL"] = "sqlite:////tmp/pf.db"; os.environ["SECRET_KEY"] = "x"
os.environ["MEDIA_ROOT"] = "/tmp/pf_media"

if os.path.exists("/tmp/pf.db"):
    os.remove("/tmp/pf.db")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from app import ai_jobs
from datetime import datetime, timedelta, date
import requests
import io

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))

db = SessionLocal()
SCHOOL = 11
now = datetime.utcnow()

s1 = User(udj_user_id=701, email="s1@t.kr", name="김학생", role=Role.student,
         school_id=SCHOOL, school_name="근명고", department="소프트웨어과",
         teacher_udj_id=901, verified=True)
s2 = User(udj_user_id=702, email="s2@t.kr", name="이학생", role=Role.student,
         school_id=SCHOOL, school_name="근명고", department="조리과",
         teacher_udj_id=902, verified=True)
tea_a = User(udj_user_id=901, email="ta@t.kr", name="A교사", role=Role.teacher,
            school_id=SCHOOL, class_name="1반")
tea_b = User(udj_user_id=902, email="tb@t.kr", name="B교사", role=Role.teacher,
            school_id=SCHOOL, class_name="2반")
tea_other_school = User(udj_user_id=903, email="to@t.kr", name="다른학교교사", role=Role.teacher,
                        school_id=999, class_name="1반")
adm = User(udj_user_id=1, email="adm@t.kr", name="관리자", role=Role.admin)
for u in (s1, s2, tea_a, tea_b, tea_other_school, adm):
    db.add(u)
db.commit(); [db.refresh(u) for u in (s1, s2, tea_a, tea_b, tea_other_school, adm)]

# 이용권(구독) — AI 기능을 쓰려면 필요하다.
db.add(SchoolSeat(school_id=SCHOOL, seats=10, started_at=now, expires_at=now + timedelta(days=300)))
db.add(SeatHolder(school_id=SCHOOL, user_id=s1.id))
db.commit()

S1H = {"Authorization": f"Bearer {create_access_token(s1)}"}
S2H = {"Authorization": f"Bearer {create_access_token(s2)}"}
TAH = {"Authorization": f"Bearer {create_access_token(tea_a)}"}
TBH = {"Authorization": f"Bearer {create_access_token(tea_b)}"}
TOH = {"Authorization": f"Bearer {create_access_token(tea_other_school)}"}
ADH = {"Authorization": f"Bearer {create_access_token(adm)}"}
db.close()
c = TestClient(app)
ai_jobs.POLL_SECONDS = 0.2
ai_jobs.start()


def wait(job_id, headers, sec=8):
    for _ in range(int(sec * 10)):
        time.sleep(0.1)
        r = c.get(f"/api/ai/jobs/{job_id}", headers=headers).json()
        if r["status"] in ("done", "failed"):
            return r
    return {"status": "timeout"}


sent_prompts = []
class Res:
    def __init__(self, b): self.status_code = 200; self._b = b
    def json(self): return self._b
def reply(body_dict):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        sent_prompts.append(json)
        return Res({"content": [{"type": "text", "text": J.dumps(body_dict, ensure_ascii=False)}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}})
    return f


print("=== 1. 준비: 학생1이 일지를 몇 개 제출한다 ===")
c.post("/api/ai/consent", json={"agreed": True}, headers=S1H)
def submit(headers, text, entry_date="2026-05-01"):
    r = c.post("/api/journals", json={"kind": "diary", "entry_date": entry_date,
        "title": "일지", "content": {"memorable": text}}, headers=headers)
    jid = r.json()["id"]
    c.post(f"/api/journals/{jid}/submit", headers=headers)
    return jid

jid1 = submit(S1H, "팀원들과 협력하여 프로젝트를 진행했다. 오류가 발생해서 원인을 찾아 고쳤다.")
jid2 = submit(S1H, "새로운 것을 스스로 찾아보며 시도해봤다.", "2026-05-02")
chk("일지 2건 준비", bool(jid1 and jid2))

print("=== 2. 포트폴리오 CRUD — 학생 본인 ===")
r = c.post("/api/portfolios", json={"title": "내 성장 기록", "theme_type": "growth",
    "purpose": "growth"}, headers=S1H)
chk("생성", r.status_code == 200, str(r.json()))
PID = r.json()["id"]
chk("표지 페이지 자동 생성", r.json()["page_count"] == 1)

r = c.post(f"/api/portfolios/{PID}/pages", json={"title": "주요 경험"}, headers=S1H)
chk("페이지 추가", r.status_code == 200, str(r.json()))
PAGE_ID = r.json()["id"]

r = c.post(f"/api/portfolio-pages/{PAGE_ID}/blocks",
          json={"block_type": "heading", "content": {"text": "제목"}}, headers=S1H)
chk("블록 추가", r.status_code == 200, str(r.json()))
BLOCK1 = r.json()["id"]
r = c.post(f"/api/portfolio-pages/{PAGE_ID}/blocks",
          json={"block_type": "text", "content": {"text": "본문"}}, headers=S1H)
BLOCK2 = r.json()["id"]

r = c.post(f"/api/portfolio-pages/{PAGE_ID}/blocks",
          json={"block_type": "not_a_real_type", "content": {}}, headers=S1H)
chk("허용 안 된 블록 종류 거부", r.status_code == 400, str(r.status_code))

print("=== 3. 블록/페이지 이동 → 순서 저장 ===")
r = c.get(f"/api/portfolios/{PID}", headers=S1H).json()
order_before = [b["id"] for b in r["pages"][1]["blocks"]]
chk("이동 전 순서", order_before == [BLOCK1, BLOCK2], str(order_before))
c.post(f"/api/portfolio-blocks/{BLOCK2}/move", json={"direction": "up"}, headers=S1H)
r = c.get(f"/api/portfolios/{PID}", headers=S1H).json()
order_after = [b["id"] for b in r["pages"][1]["blocks"]]
chk("블록 이동 후 순서 바뀜·저장됨", order_after == [BLOCK2, BLOCK1], str(order_after))

r = c.post(f"/api/portfolios/{PID}/pages", json={"title": "결과"}, headers=S1H)
PAGE2 = r.json()["id"]
pages_before = [p["id"] for p in c.get(f"/api/portfolios/{PID}", headers=S1H).json()["pages"]]
c.post(f"/api/portfolio-pages/{PAGE2}/move", json={"direction": "up"}, headers=S1H)
pages_after = [p["id"] for p in c.get(f"/api/portfolios/{PID}", headers=S1H).json()["pages"]]
chk("페이지 이동 후 순서 바뀜·저장됨", pages_before != pages_after, str((pages_before, pages_after)))

print("=== 4. 학생 A는 학생 B 포트폴리오/이미지 접근 불가 ===")
r = c.get(f"/api/portfolios/{PID}", headers=S2H)
chk("남의 포트폴리오 조회 차단", r.status_code == 404, str(r.status_code))
r = c.put(f"/api/portfolios/{PID}", json={"title": "몰래 고치기"}, headers=S2H)
chk("남의 포트폴리오 수정 차단", r.status_code == 404, str(r.status_code))
r = c.delete(f"/api/portfolios/{PID}", headers=S2H)
chk("남의 포트폴리오 삭제 차단", r.status_code == 404, str(r.status_code))

print("=== 5. 이미지 업로드 — 저장/썸네일/표시 ===")
from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (800, 600), color=(10, 20, 30)).save(buf, "JPEG")
buf.seek(0)
r = c.post("/api/portfolio-images",
          data={"portfolio_id": str(PID), "title": "표지 사진"},
          files={"file": ("a.jpg", buf, "image/jpeg")}, headers=S1H)
chk("업로드 성공", r.status_code == 200, str(r.json()))
IMG_ID = r.json()["id"]
chk("가로세로 저장됨", r.json()["width"] == 800 and r.json()["height"] == 600, str(r.json()))

r = c.get(f"/api/portfolio-images/{IMG_ID}?variant=thumbnail", headers=S1H)
chk("썸네일 조회됨", r.status_code == 200 and len(r.content) > 0)
r = c.get(f"/api/portfolio-images/{IMG_ID}", headers=S2H)
chk("남의 사진(비공개) 접근 차단", r.status_code == 404, str(r.status_code))

not_image = io.BytesIO(b"not an image at all")
r = c.post("/api/portfolio-images", data={"portfolio_id": str(PID)},
          files={"file": ("a.jpg", not_image, "image/jpeg")}, headers=S1H)
chk("이미지 아닌 파일 거부", r.status_code == 400, str(r.status_code))

print("=== 6. 공유 — 보기 전용, 링크 없으면 비공개 ===")
r = c.get(f"/api/portfolio-share/{'x'*20}")
chk("공유 안 한 링크는 404", r.status_code == 404)
r = c.post(f"/api/portfolios/{PID}/share", headers=S1H)
token = r.json()["share_token"]
r = c.get(f"/api/portfolio-share/{token}")
chk("공유 링크는 로그인 없이 조회됨", r.status_code == 200, str(r.status_code))
r = c.get(f"/api/portfolio-images/{IMG_ID}?variant=thumbnail", headers=S2H)
chk("공유 상태에선 다른 학생도 사진 조회 가능(보기만)", r.status_code == 200)
r = c.get(f"/api/portfolio-images/{IMG_ID}?variant=thumbnail")
chk("공유 상태에선 로그인 없이도 사진 조회 가능(<img> 태그는 인증 헤더를 못 붙임)",
    r.status_code == 200, str(r.status_code))
r = c.put(f"/api/portfolios/{PID}", json={"title": "공유돼도 못 고침"}, headers=S2H)
chk("공유돼도 남은 수정 못 함(보기 전용)", r.status_code == 404, str(r.status_code))
c.delete(f"/api/portfolios/{PID}/share", headers=S1H)
r = c.get(f"/api/portfolio-share/{token}")
chk("공유 끄면 즉시 안 열림", r.status_code == 404)
r = c.get(f"/api/portfolio-images/{IMG_ID}?variant=thumbnail")
chk("공유 끄면 로그인 없는 사진 조회도 막힘", r.status_code == 404, str(r.status_code))

print("=== 7. 교사 관찰 기록 — 작성 교사 본인만 ===")
r = c.post("/api/teacher/observations", json={
    "student_id": s1.id, "observed_at": "2026-03-12", "title": "실습 관찰",
    "content": "배선 순서를 혼동했으나 회로도를 다시 확인하며 작업을 수정함."}, headers=TAH)
chk("A교사 작성", r.status_code == 200, str(r.json()))
OBS_ID = r.json()["id"]
chk("날짜가 저장됨", r.json()["observed_at"] == "2026-03-12", str(r.json()))
r = c.post("/api/teacher/observations", json={
    "student_id": s1.id, "observed_at": "2026-03-26",
    "content": "작업 전에 회로도를 먼저 확인하는 모습이 관찰됨."}, headers=TAH)
chk("A교사 두 번째 기록 작성", r.status_code == 200, str(r.json()))

r = c.get("/api/teacher/observations", params={"student_id": s1.id}, headers=TAH)
chk("A교사 본인 조회 — 2건 모두 보임", r.status_code == 200 and len(r.json()) == 2, str(r.json()))
r = c.get("/api/teacher/observations", params={"student_id": s1.id, "order": "asc"}, headers=TAH)
chk("오래된순 정렬", r.status_code == 200 and r.json()[0]["observed_at"] == "2026-03-12", str(r.json()))
r = c.get("/api/teacher/observations", params={"student_id": s1.id, "q": "회로도"}, headers=TAH)
chk("키워드 검색 — 둘 다 걸림", len(r.json()) == 2, str(r.json()))
r = c.get("/api/teacher/observations", params={"student_id": s1.id, "q": "혼동"}, headers=TAH)
chk("키워드 검색 — 하나만 걸림", len(r.json()) == 1, str(r.json()))

r = c.get(f"/api/teacher/observations/{OBS_ID}", headers=TAH)
chk("단건 조회(본인)", r.status_code == 200, str(r.status_code))

r = c.get("/api/teacher/observations", params={"student_id": s1.id}, headers=TBH)
chk("B교사는 담당 학생이 아니라 학생 자체를 못 봄", r.status_code == 403, str(r.status_code))
r = c.get(f"/api/teacher/observations/{OBS_ID}", headers=TBH)
chk("B교사 — 남의 기록 단건 조회 차단(403)", r.status_code == 403, str(r.status_code))
r = c.put(f"/api/teacher/observations/{OBS_ID}", json={"content": "몰래 고치기"}, headers=TBH)
chk("B교사 — 남의 기록 수정 차단(403)", r.status_code == 403, str(r.status_code))
r = c.delete(f"/api/teacher/observations/{OBS_ID}", headers=TBH)
chk("B교사 — 남의 기록 삭제 차단(403)", r.status_code == 403, str(r.status_code))

r = c.get("/api/teacher/observations", params={"student_id": s1.id}, headers=S1H)
chk("학생은 관찰 기록 API 자체를 못 씀", r.status_code == 403, str(r.status_code))
r = c.get("/api/teacher/observations", params={"student_id": s1.id}, headers=ADH)
chk("관리자도 관찰 기록 원문 조회 불가", r.status_code == 403, str(r.status_code))
r = c.get(f"/api/teacher/observations/{OBS_ID}", headers=ADH)
chk("관리자 — 단건 조회도 불가", r.status_code == 403, str(r.status_code))

r = c.put(f"/api/teacher/observations/{OBS_ID}", json={"content": "고친 내용"}, headers=TAH)
chk("본인 수정은 됨", r.status_code == 200 and r.json()["content"] == "고친 내용", str(r.json()))

print("=== 8. 담당 아닌 학생 · 다른 학교 교사 ===")
r = c.post("/api/teacher/observations", json={"student_id": s2.id, "content": "몰래"}, headers=TAH)
chk("같은 학교, 담당 아닌 학생에 대한 기록 작성 차단", r.status_code == 403, str(r.status_code))
r = c.post("/api/teacher/observations", json={"student_id": s1.id, "content": "몰래"}, headers=TOH)
chk("다른 학교 교사는 학생 자체를 못 찾음", r.status_code == 403, str(r.status_code))
r = c.get("/api/teacher/observations", params={"student_id": s1.id}, headers=TOH)
chk("다른 학교 교사 — 목록 조회도 차단", r.status_code == 403, str(r.status_code))

print("=== 8-1. 학급 전체 보기(요약) — 본인 기록만 센다 ===")
r = c.get("/api/teacher/observations/summary", headers=TAH)
chk("요약 조회됨", r.status_code == 200, str(r.json()))
row = next((x for x in r.json() if x["student_id"] == s1.id), None)
chk("학생1 기록 수 2건(본인이 쓴 것만)", row and row["count"] == 2, str(row))
r = c.get(f"/api/teacher/students/{s1.id}/observations", headers=TAH)
chk("학생별 경로 별칭도 같은 결과", r.status_code == 200 and len(r.json()) == 2, str(r.json()))

print("=== 8-2. 개인 문구 템플릿 ===")
r = c.post("/api/teacher/observation-templates", json={"title": "문제 해결", "content": "스스로 원인을 확인하고 해결을 시도함."}, headers=TAH)
chk("템플릿 저장", r.status_code == 200, str(r.json()))
TPL_ID = r.json()["id"]
r = c.get("/api/teacher/observation-templates", headers=TBH)
chk("다른 교사에게는 안 보임", r.status_code == 200 and len(r.json()) == 0, str(r.json()))
r = c.delete(f"/api/teacher/observation-templates/{TPL_ID}", headers=TAH)
chk("본인은 삭제 가능", r.status_code == 200)

print("=== 8-3. 교사 관찰 기록은 학생 포트폴리오 AI에 절대 재료로 쓰이지 않는다 ===")
c.post("/api/teacher/observations", json={
    "student_id": s1.id, "content": "이비밀관찰문구는절대AI에안보여야함"}, headers=TAH)

print("=== 9. AI 작업 중복 방지 ===")
db = SessionLocal()
j1 = ai_jobs.enqueue(db, s1.id, "theme_recommend", {}, dedup_key="theme_recommend")
j2 = ai_jobs.enqueue(db, s1.id, "theme_recommend", {}, dedup_key="theme_recommend")
chk("같은 dedup_key면 같은 작업을 돌려줌(중복 생성 안 함)", j1.id == j2.id, str((j1.id, j2.id)))
db.query(AiJob).filter(AiJob.id == j1.id).delete()
db.commit(); db.close()

print("=== 10. 테마 추천 — 서버가 1차로 후보를 거르고, AI는 문구만 ===")
requests.post = reply({"recommendations": [
    {"theme_type": "problem_solving", "reason": "문제를 해결한 기록이 있습니다."},
    {"theme_type": "collaboration", "reason": "팀원들과 협력한 기록이 있습니다."},
]})
r = c.post("/api/portfolio-theme-recommendations", headers=S1H)
chk("테마 추천 요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], S1H)
chk("생성 완료", job["status"] == "done", str(job)[:200])
recs = job["result"]["recommendations"]
chk("추천에 관련 기록 수가 담김(점수 아님)", all("source_count" in x for x in recs), str(recs))
chk("학생 평가 문구(점수) 노출 안 함", not any("점" in x.get("reason", "") for x in recs), str(recs))

r = c.get("/api/portfolio-theme-recommendations", headers=S1H)
chk("캐시된 추천 재조회 가능", r.status_code == 200 and len(r.json()) > 0, str(r.json()))
chk("테마 추천에 교사 관찰 기록 문구가 새지 않음",
    not any("이비밀관찰문구" in str(p) for p in sent_prompts), "leaked")

print("=== 11. 포트폴리오 AI 생성 — 고른 기록만 근거로 ===")
sent_prompts.clear()
requests.post = reply({
    "title": "협력과 문제 해결 기록",
    "description": "팀 프로젝트에서 있었던 일을 정리했습니다.",
    "pages": [
        {"title": "프로젝트 소개", "blocks": [
            {"type": "heading", "content": "팀 프로젝트"},
            {"type": "text", "content": "팀원들과 협력하여 문제를 해결했습니다."},
        ], "source_journal_ids": [jid1]},
    ],
})
r = c.post("/api/portfolios/generate", json={"theme_type": "collaboration", "purpose": "employment",
    "journal_ids": [jid1]}, headers=S1H)
chk("생성 요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], S1H)
chk("생성 완료", job["status"] == "done", str(job)[:200])
GEN_PID = job["result"]["portfolio_id"]
r = c.get(f"/api/portfolios/{GEN_PID}", headers=S1H)
chk("만들어진 포트폴리오 조회됨", r.status_code == 200 and len(r.json()["pages"]) == 1, str(r.json()))
chk("다른 학생 기록은 보내지 않음(본인 것만)",
    not any("s2" in str(p) for p in sent_prompts), "leaked")
chk("포트폴리오 생성에도 교사 관찰 기록 문구가 새지 않음",
    not any("이비밀관찰문구" in str(p) for p in sent_prompts), "leaked")

print("=== 12. 경험 추출 ===")
requests.post = reply({"title": "협업 경험", "type": "collaboration",
    "situation": "팀 프로젝트", "problem": "오류 발생",
    "action": "원인을 찾아 고침", "result": "문제 해결", "lesson": "협업의 중요성을 느낌"})
r = c.post("/api/experiences/extract", json={"journal_id": jid1}, headers=S1H)
chk("요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], S1H)
chk("생성 완료", job["status"] == "done", str(job)[:200])
EXP_ID = job["result"]["experience_id"]
r = c.get(f"/api/experiences/{EXP_ID}/sources", headers=S1H)
chk("근거 원본 조회됨", r.status_code == 200 and len(r.json()) == 1, str(r.json()))
r = c.get("/api/experiences", headers=S2H)
chk("다른 학생은 자기 경험만 봄(0건)", r.status_code == 200 and len(r.json()) == 0, str(r.json()))

print("=== 13. 글 첨삭 — 허용된 동작만 ===")
requests.post = reply({"result": "다듬어진 문장입니다."})
r = c.post("/api/portfolio-text/proofread", json={"text": "원문", "action": "TEXT_EDIT"}, headers=S1H)
job = wait(r.json()["job_id"], S1H)
chk("첨삭 완료", job["status"] == "done", str(job)[:150])
r = c.post("/api/portfolio-text/proofread", json={"text": "원문", "action": "DO_ANYTHING"}, headers=S1H)
chk("허용 안 된 동작 거부(422)", r.status_code == 422, str(r.status_code))

print("=== 14. 사진 설명 — 사진과 함께 보냈는지 ===")
sent_prompts.clear()
requests.post = reply({"caption": "책상 위 노트북 사진입니다."})
r = c.post(f"/api/portfolio-images/{IMG_ID}/caption", headers=S1H)
chk("요청 접수", r.status_code == 200, str(r.json()))
job = wait(r.json()["job_id"], S1H)
chk("생성 완료", job["status"] == "done", str(job)[:150])
chk("사진(base64)을 실제로 함께 보냄",
    any(isinstance(p.get("messages", [{}])[0].get("content"), list) for p in sent_prompts),
    str(sent_prompts)[:200])

print("=== 15. AI 이용권 없는 학생은 AI 기능 차단, 골격은 그대로 됨 ===")
r = c.post("/api/portfolios", json={"title": "이용권 없어도 됨", "theme_type": "custom",
    "purpose": "free"}, headers=S2H)
chk("이용권 없어도 포트폴리오는 만들 수 있음(일지처럼 무료)", r.status_code == 200, str(r.json()))
r = c.post("/api/portfolio-theme-recommendations", headers=S2H)
chk("이용권 없으면 AI 추천은 막힘", r.status_code == 402, str(r.status_code))

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
