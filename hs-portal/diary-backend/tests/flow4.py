import os,sys,json,time
os.environ["DATABASE_URL"]="sqlite:////tmp/f4.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/f4.db"):
    os.remove("/tmp/f4.db")
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
for i,(txt) in enumerate([
  "조별 과제에서 자료 정리를 맡았습니다. 팀원이 늦어져 제가 정리했고 발표를 마쳤습니다.",
  "선반 실습에서 치수가 0.2mm 커서 세 번 다시 했습니다. 이송 속도를 줄이니 맞았습니다."]):
    db.add(JournalEntry(user_id=stu.id,kind="diary",entry_date=date(2026,5,i+1),
      content=json.dumps({"memorable":txt},ensure_ascii=False)))
db.commit()
SH={"Authorization":f"Bearer {create_access_token(stu)}"}
db.close()
c=TestClient(app); ai_jobs.POLL_SECONDS=0.2; ai_jobs.start()

class Res:
    def __init__(self,b): self.status_code=200; self._b=b
    def json(self): return self._b
def reply(fn):
    def f(url, headers=None, json=None, timeout=None):
        import json as J
        return Res({"content":[{"type":"text","text":J.dumps(fn(json["messages"][0]["content"]),ensure_ascii=False)}],
                    "usage":{"input_tokens":1,"output_tokens":1}})
    return f
def wait(jid, sec=8):
    for _ in range(int(sec*10)):
        time.sleep(0.1)
        r=c.get(f"/api/ai/jobs/{jid}", headers=SH).json()
        if r["status"] in ("done","failed"): return r
    return {"status":"timeout"}

print("=== 화면이 쓰는 흐름 그대로 ===")
st=c.get("/api/ai/status", headers=SH).json()
# 가입하면 처음부터 동의 상태다 — 화면이 동의 창을 안 띄우고 바로 시작한다.
chk("① 상태 조회", st["available"] is True and st["consented"] is True, str(st))

c.post("/api/ai/consent", json={"agreed":True}, headers=SH)
chk("② 동의", c.get("/api/ai/status", headers=SH).json()["consented"] is True)

mats=c.get("/api/cover-letters/materials", params={"topic":"teamwork"}, headers=SH).json()
t=mats["topics"][0]
chk("③ 재료에 journal_id 있음",
    t["matches"] and "journal_id" in t["matches"][0], str(t["matches"][:1])[:120])
JID=t["matches"][0]["journal_id"]

requests.post = reply(lambda b: {
 "cleaned_content":"조별 과제에서 자료 정리를 맡았습니다. 팀원의 진행이 늦어져 제가 정리를 이어받았고, 발표를 예정대로 마쳤습니다.",
 "inappropriate":[],
 "experience":{"situation":"조별 과제","problem":"팀원 진행 지연","goal":"발표 준비",
               "action":"자료를 대신 정리","result":"발표 완료","emotion":"부담",
               "lesson":"미리 확인하는 것이 중요"},
 "skills":[{"name":"책임감","evidence":"맡은 일을 끝까지 함","confidence":0.85}],
 "keywords":["조별과제"]})
r=c.post(f"/api/journals/{JID}/analyze", headers=SH).json()
res=wait(r["job_id"]) if r["status"]=="queued" else {"status":"done","result":r["result"]}
d=res["result"]
chk("④ 분석 결과", res["status"]=="done", str(res)[:100])
chk("   원문 함께", "밤" in d["original_content"] or "팀원이 늦어져" in d["original_content"])
chk("   다듬은 글", d["cleaned_content"] != d["original_content"])
chk("   경험 5칸", all(d["experience"].get(k) for k in ("situation","problem","action","result","lesson")))
chk("   역량 근거", d["skills"][0]["evidence"])

def essay(b):
    if "검사자" in b: return {"safe":True,"issues":[]}
    return {"draft":"조별 과제에서 자료 정리를 맡았습니다. 팀원의 진행이 늦어지자 정리를 이어받아 발표를 예정대로 마쳤습니다.",
            "facts_used":["자료를 대신 정리"],"warnings":[]}
requests.post = reply(essay)
r=c.post("/api/cover-letters/generate", json={
  "question":"팀 활동에서 본인의 역할을 책임감 있게 수행했던 경험",
  "journal_ids":[JID],"character_limit":500}, headers=SH).json()
res=wait(r["job_id"])
chk("⑤ 초안", res["status"]=="done" and res["result"]["draft"], str(res)[:100])
chk("   사실 확인됨", res["result"]["safe"] is True)
chk("   글자 수", res["result"]["character_count"]<=500)

print("=== 동의 거두면 ===")
c.post("/api/ai/consent", json={"agreed":False}, headers=SH)
chk("⑥ 다시 막힘", c.post(f"/api/journals/{JID}/analyze", headers=SH).status_code==403)
chk("   기존 기능 정상", c.get("/api/cover-letters/materials", headers=SH).status_code==200)

print("=== 경험을 여러 개 고를 때 ===")
c.post("/api/ai/consent", json={"agreed":True}, headers=SH)
db=SessionLocal(); ids=[j.id for j in db.query(JournalEntry).all()]; db.close()
requests.post = reply(essay)
r=c.post("/api/cover-letters/generate", json={
  "question":"문제 해결","journal_ids":ids,"character_limit":800}, headers=SH).json()
res=wait(r["job_id"])
chk("⑦ 여러 경험으로", res["status"]=="done", str(res)[:80])
r=c.post("/api/cover-letters/generate", json={
  "question":"q","journal_ids":[1,2,3,4,5,6]}, headers=SH)
chk("   6개는 거부", r.status_code==400, str(r.status_code))
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
