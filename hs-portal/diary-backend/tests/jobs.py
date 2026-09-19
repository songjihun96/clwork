import os,sys,time,json
os.environ["DATABASE_URL"]="sqlite:////tmp/jb.db"; os.environ["SECRET_KEY"]="x"

# 앞선 검사의 자료가 남아 있으면 결과가 달라져,
# 멀쩡한 코드가 실패한 것처럼 보인다. 먼저 지운다.
if os.path.exists("/tmp/jb.db"):
    os.remove("/tmp/jb.db")
sys.path.insert(0,".")
from app.database import SessionLocal, Base, engine
from app.models import *
from app import ai_jobs
Base.metadata.create_all(engine)
OK=[]
def chk(n,c,e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL")+f"  {n}"+(f"  {e}" if not c and e else ""))

db=SessionLocal()
u=User(udj_user_id=1,email="s@t.kr",name="홍길동",role=Role.student)
db.add(u); db.commit(); db.refresh(u); UID=u.id; db.close()

print("=== 1. 적어 두고 바로 돌아온다 ===")
db=SessionLocal()
t=time.time(); job=ai_jobs.enqueue(db,UID,"test",{"a":1}); ms=(time.time()-t)*1000
chk("즉시 응답", ms<200, f"{ms:.0f}ms")
chk("기다리는 중", job.status=="queued")
JID=job.id; db.close()

print("=== 2. 일꾼이 처리한다 ===")
done=[]
def handler(db,user_id,payload):
    done.append(payload); time.sleep(0.1)
    return {"ok":True,"echo":payload}
ai_jobs.register("test", handler)
ai_jobs.POLL_SECONDS=0.2
ai_jobs.start()
for _ in range(40):
    time.sleep(0.1)
    db=SessionLocal(); j=db.get(AiJob,JID); st=j.status; db.close()
    if st in ("done","failed"): break
chk("끝났다", st=="done", st)
db=SessionLocal(); j=db.get(AiJob,JID)
chk("결과 담김", json.loads(j.result_json)["echo"]=={"a":1}, j.result_json)
db.close()

print("=== 3. 실패해도 일꾼이 안 죽는다 ===")
def boom(db,user_id,payload): raise ValueError("일부러 낸 오류")
ai_jobs.register("boom", boom)
db=SessionLocal(); bad=ai_jobs.enqueue(db,UID,"boom",{}); BID=bad.id; db.close()
for _ in range(40):
    time.sleep(0.1)
    db=SessionLocal(); st=db.get(AiJob,BID).status; db.close()
    if st in ("done","failed"): break
chk("실패로 기록", st=="failed", st)
db=SessionLocal(); j=db.get(AiJob,BID)
chk("친절한 안내", "다시" in j.error, j.error)
chk("오류 내용 안 새어나감", "일부러" not in j.error, j.error)
db.close()

print("=== 4. 일꾼이 계속 살아 있다 ===")
db=SessionLocal(); nxt=ai_jobs.enqueue(db,UID,"test",{"b":2}); NID=nxt.id; db.close()
for _ in range(40):
    time.sleep(0.1)
    db=SessionLocal(); st=db.get(AiJob,NID).status; db.close()
    if st in ("done","failed"): break
chk("실패 뒤에도 처리", st=="done", st)

print("=== 5. 모르는 종류 ===")
db=SessionLocal(); un=ai_jobs.enqueue(db,UID,"없는것",{}); UNID=un.id; db.close()
for _ in range(40):
    time.sleep(0.1)
    db=SessionLocal(); st=db.get(AiJob,UNID).status; db.close()
    if st in ("done","failed"): break
chk("실패 처리", st=="failed", st)

print("=== 6. 같은 작업을 두 번 하지 않는다 ===")
count=[]
def slow(db,user_id,payload):
    count.append(1); time.sleep(0.3); return {"ok":True}
ai_jobs.register("slow", slow)
db=SessionLocal(); s1=ai_jobs.enqueue(db,UID,"slow",{}); SID=s1.id; db.close()
import threading
for _ in range(3):
    threading.Thread(target=ai_jobs._run_once, daemon=True).start()
time.sleep(1.2)
chk("한 번만 처리", len(count)==1, f"{len(count)}번")

print("=== 7. 멈춘 작업 정리 ===")
from datetime import datetime, timedelta
db=SessionLocal()
stuck=AiJob(user_id=UID,kind="test",status="running",
            started_at=datetime.utcnow()-timedelta(minutes=30))
db.add(stuck); db.commit(); db.refresh(stuck); STID=stuck.id; db.close()
ai_jobs._cleanup()
db=SessionLocal(); chk("죽은 작업 실패 처리", db.get(AiJob,STID).status=="failed"); db.close()

ai_jobs.stop()
print(); print(f"===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
