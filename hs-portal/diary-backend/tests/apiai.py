import os,sys,json,time
os.environ["DATABASE_URL"]="sqlite:////tmp/aa.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/aa.db"):
    os.remove("/tmp/aa.db")
os.environ["ANTHROPIC_API_KEY"]="test-key"
for k in ("TOSS_SECRET_KEY","TOSS_CLIENT_KEY"): os.environ.pop(k,None)
sys.path.insert(0,".")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import *
from app.auth import create_access_token
from app import ai_jobs
from datetime import datetime, timedelta, date
import requests
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
stu=User(udj_user_id=3,email="s@t.kr",name="홍길동",role=Role.student,
         school_id=7,school_name="근명고등학교",verified=True)
db.add(stu); db.commit(); db.refresh(stu)
now=datetime.utcnow()
db.add(SchoolSeat(school_id=7,seats=5,started_at=now,expires_at=now+timedelta(days=300)))
db.add(SeatHolder(school_id=7,user_id=stu.id))
j=JournalEntry(user_id=stu.id,kind="diary",entry_date=date(2026,5,1),
  content=json.dumps({"memorable":"조별 과제에서 자료 정리를 맡았습니다. 팀원이 늦어져 제가 밤늦게까지 정리했고, 발표는 예정대로 마쳤습니다."},ensure_ascii=False))
db.add(j); db.commit(); db.refresh(j); JID=j.id
db.commit()
SH={"Authorization":f"Bearer {create_access_token(stu)}"}
db.close()
c=TestClient(app)
ai_jobs.POLL_SECONDS=0.2
# 실제 서버는 startup 에서 일꾼을 띄운다. 테스트에서는 직접 띄운다.
ai_jobs.start()

def wait(job_id, sec=8):
    for _ in range(int(sec*10)):
        time.sleep(0.1)
        r=c.get(f"/api/ai/jobs/{job_id}", headers=SH).json()
        if r["status"] in ("done","failed"): return r
    return {"status":"timeout"}

class Res:
    def __init__(self,b): self.status_code=200; self._b=b
    def json(self): return self._b
def reply(fn):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        return Res({"content":[{"type":"text","text":J.dumps(fn(json["messages"][0]["content"]),ensure_ascii=False)}],
                    "usage":{"input_tokens":1,"output_tokens":1}})
    return f

# 가입하면 처음부터 동의 상태다(자기소개서 화면에서 벽을 한 번 더 세우지
# 않는다). 확인할 것은 그 반대편 — **거두면 진짜로 막히는가** 이다.
print("=== 1. 거두면 막힌다 ===")
st=c.get("/api/ai/status", headers=SH).json()
chk("처음엔 동의 상태", st["consented"] is True, str(st))
c.post("/api/ai/consent", json={"agreed":False}, headers=SH)
st=c.get("/api/ai/status", headers=SH).json()
chk("거두면 동의 아님", st["consented"] is False, str(st))
r=c.post(f"/api/journals/{JID}/analyze", headers=SH)
chk("분석 거부", r.status_code==403 and "동의" in r.json()["detail"], str(r.json()))
r=c.post("/api/cover-letters/generate", json={"question":"q","journal_ids":[JID]}, headers=SH)
chk("초안도 거부", r.status_code==403)

print("=== 2. 다시 동의 ===")
r=c.post("/api/ai/consent", json={"agreed":True}, headers=SH).json()
chk("동의됨", r["consented"] is True, str(r))
chk("상태 반영", c.get("/api/ai/status", headers=SH).json()["consented"] is True)

print("=== 3. 일지 분석 ===")
requests.post = reply(lambda body: {
 "cleaned_content":"조별 과제에서 자료 정리를 맡았습니다. 팀원의 진행이 늦어져 늦게까지 정리했고, 발표를 예정대로 마쳤습니다.",
 "inappropriate":[],
 "experience":{"situation":"조별 과제","problem":"팀원 진행 지연","goal":"발표 준비",
               "action":"자료를 대신 정리","result":"발표 완료","emotion":"부담",
               "lesson":"미리 확인하는 것이 중요"},
 "skills":[{"name":"책임감","evidence":"맡은 일을 끝까지 함","confidence":0.85}],
 "keywords":["조별과제","자료정리"]})
r=c.post(f"/api/journals/{JID}/analyze", headers=SH).json()
chk("맡겨짐", r["status"]=="queued", str(r))
res=wait(r["job_id"])
chk("끝남", res["status"]=="done", str(res)[:120])
d=res["result"]
chk("경험 구조화", d["experience"]["action"]=="자료를 대신 정리", str(d["experience"]))
chk("역량 근거 있음", d["skills"][0]["evidence"], str(d["skills"]))
chk("원문 보관", "밤늦게까지" in d["original_content"], d["original_content"][:60])

print("=== 4. 같은 일지는 다시 안 부른다 ===")
calls=[]
requests.post = reply(lambda body: (calls.append(1), {"cleaned_content":"x"})[1])
r=c.post(f"/api/journals/{JID}/analyze", headers=SH).json()
chk("저장해 둔 것 사용", r["status"]=="done" and r["cached"] is True, str(r)[:80])
chk("AI 안 부름", len(calls)==0, f"{len(calls)}번 부름")

print("=== 5. 글이 바뀌면 다시 분석 ===")
c.put(f"/api/journals/{JID}", json={"kind":"diary","entry_date":"2026-05-01","title":"고친 글",
  "content":{"memorable":"내용을 고쳤습니다. 조별 과제에서 발표 자료를 맡아 정리했습니다."}}, headers=SH)
requests.post = reply(lambda body: {"cleaned_content":"고친 글","experience":{},"skills":[],"keywords":[]})
r=c.post(f"/api/journals/{JID}/analyze", headers=SH).json()
chk("다시 맡김", r["status"]=="queued" and r["cached"] is False, str(r)[:80])
wait(r["job_id"])

print("=== 6. 자소서 초안 ===")
def essay(body):
    if "검사자" in body: return {"safe":True,"issues":[]}
    return {"draft":"조별 과제에서 자료 정리를 맡았습니다. 팀원의 진행이 늦어지자 제가 정리를 이어받아 발표를 예정대로 마쳤습니다.",
            "facts_used":["자료를 대신 정리"],"warnings":[]}
requests.post = reply(essay)
r=c.post("/api/cover-letters/generate", json={
  "question":"팀 활동에서 본인의 역할을 책임감 있게 수행했던 경험",
  "journal_ids":[JID],"character_limit":500}, headers=SH).json()
chk("맡겨짐", r["status"]=="queued", str(r))
res=wait(r["job_id"])
chk("초안 나옴", res["status"]=="done" and res["result"]["draft"], str(res)[:120])
chk("검증됨", res["result"]["safe"] is True)
chk("글자 수 셈", res["result"]["character_count"]==len(res["result"]["draft"]))

print("=== 7. 사실 검증 ===")
requests.post = reply(lambda b: {"safe":False,
  "issues":[{"text":"팀장으로서","reason":"원문에 없는 역할"}]})
r=c.post("/api/cover-letters/verify", json={
  "draft":"팀장으로서 팀을 이끌었습니다.","journal_ids":[JID]}, headers=SH).json()
res=wait(r["job_id"])
chk("지어낸 것 잡음", res["result"]["safe"] is False, str(res["result"]))
chk("이유 알려줌", "원문에 없는" in res["result"]["issues"][0]["reason"])

print("=== 8. 동의 철회 ===")
c.post("/api/ai/consent", json={"agreed":False}, headers=SH)
r=c.post(f"/api/journals/{JID}/analyze", headers=SH)
chk("다시 막힘", r.status_code==403, str(r.status_code))
db=SessionLocal(); cs=db.query(AiConsent).first()
chk("철회 기록 남음", cs.revoked_at is not None and cs.agreed is False); db.close()

print("=== 9. 남의 것은 못 본다 ===")
db=SessionLocal()
other=User(udj_user_id=99,email="o@t.kr",name="남",role=Role.student,school_id=7)
db.add(other); db.commit(); db.refresh(other)
db.add(SeatHolder(school_id=7,user_id=other.id)); db.commit()
OH={"Authorization":f"Bearer {create_access_token(other)}"}
jid=db.query(AiJob).first().id; db.close()
chk("남의 작업 못 봄", c.get(f"/api/ai/jobs/{jid}", headers=OH).status_code==404)

print("=== 10. 키가 없으면 ===")
from app import llm
llm.API_KEY=""
llm.API_KEYS=[]  # available()은 이제 API_KEYS(여러 계정 키 목록)를 본다
r=c.post("/api/ai/consent", json={"agreed":True}, headers=SH)
r=c.post(f"/api/journals/{JID}/analyze", headers=SH)
chk("준비 안 됐다고 알림", r.status_code==503, str(r.status_code))
chk("일지 기능은 정상", c.get("/api/journals", headers=SH).status_code==200)
chk("자소서 기능도 정상", c.get("/api/cover-letters", headers=SH).status_code==200)
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
