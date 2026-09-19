"""AI 작업 큐의 redis 백엔드 검사.

실제 Redis 서버 없이, lpush/brpop 만 흉내 내는 가짜 클라이언트로 검사한다
(그 두 메서드만 ai_jobs.py 가 실제로 쓴다). 확인할 것: (1) enqueue 가
redis 로 작업 id 를 보낸다, (2) claim 이 queued→running 을 원자적으로
바꾼다(이미 가져간 건 못 가져간다), (3) execute 가 결과를 표에 남긴다,
(4) redis push 가 실패해도 표에는 남아 있어 나중에 sweep 으로 복구된다,
(5) job_out 은 백엔드와 무관하게 표(DB)만 보고 응답한다.
"""
import os, sys, threading, time
os.environ["DATABASE_URL"] = "sqlite:////tmp/ai_queue_redis.db"; os.environ["SECRET_KEY"] = "x"
os.environ["AI_QUEUE_BACKEND"] = "redis"

if os.path.exists("/tmp/ai_queue_redis.db"):
    os.remove("/tmp/ai_queue_redis.db")
sys.path.insert(0, ".")
from app.main import app  # noqa: F401 — 임포트만으로 테이블 생성 + 핸들러 등록이 일어난다
from app.database import SessionLocal
from app.models import User, Role, AiJob
from app import ai_jobs

OK = []
def chk(n, c, e=""):
    OK.append(bool(c)); print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


class FakeRedis:
    """lpush(앞에 넣기) + brpop(뒤에서 빼기) = FIFO. 진짜 Redis 리스트와 같은 순서."""
    def __init__(self):
        self._list = []
        self._lock = threading.Lock()
        self.push_should_fail = False

    def lpush(self, key, value):
        if self.push_should_fail:
            raise ConnectionError("일부러 실패")
        with self._lock:
            self._list.insert(0, str(value).encode())

    def brpop(self, key, timeout=1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._list:
                    return (key.encode(), self._list.pop())
            time.sleep(0.02)
        return None


fake = FakeRedis()
ai_jobs._redis_client = fake  # _get_redis() 가 이미 있으면 새로 안 만든다

chk("모듈이 redis 백엔드로 설정됨", ai_jobs.QUEUE_BACKEND == "redis", ai_jobs.QUEUE_BACKEND)

db = SessionLocal()
stu = User(udj_user_id=1, email="q@t.kr", name="큐학생", role=Role.student, verified=True)
db.add(stu); db.commit(); db.refresh(stu)
UID = stu.id
db.close()

captured = []
def echo_handler(db, user_id, payload):
    captured.append(payload)
    return {"ok": True, "echo": payload.get("x")}

def fail_handler(db, user_id, payload):
    return {"ok": False, "error": "일부러 실패"}

ai_jobs.register("test_echo", echo_handler)
ai_jobs.register("test_fail", fail_handler)

print("=== 1. enqueue 가 redis 로 작업 id 를 보낸다 ===")
db = SessionLocal()
job = ai_jobs.enqueue(db, UID, "test_echo", {"x": 42})
chk("표에 queued 로 생김", job.status == "queued")
chk("redis 큐에 정확히 이 id 가 들어감", len(fake._list) == 1 and fake._list[0] == str(job.id).encode())
JOB_ID = job.id
db.close()

print("=== 2. claim 은 원자적 — 같은 작업을 두 번 못 가져간다 ===")
db1 = SessionLocal()
db2 = SessionLocal()
claimed1 = ai_jobs._claim(db1, JOB_ID)
claimed2 = ai_jobs._claim(db2, JOB_ID)
chk("첫 claim은 성공", claimed1 is not None and claimed1.status == "running")
chk("두번째 claim은 실패(None)", claimed2 is None)
db1.close(); db2.close()

print("=== 3. execute 가 처리 결과를 표에 남긴다 ===")
db = SessionLocal()
job = db.query(AiJob).filter(AiJob.id == JOB_ID).first()
ai_jobs._execute(db, job)
chk("처리 함수가 실제로 불림", captured == [{"x": 42}])
chk("상태가 done 으로 바뀜", job.status == "done")
out = ai_jobs.job_out(job, db)
chk("결과가 job_out 에 담김", out["result"].get("echo") == 42, str(out))
db.close()

print("=== 4. 실패한 작업도 표에 남는다 ===")
db = SessionLocal()
job2 = ai_jobs.enqueue(db, UID, "test_fail", {})
claimed = ai_jobs._claim(db, job2.id)
ai_jobs._execute(db, claimed)
chk("실패로 표시됨", claimed.status == "failed")
chk("에러 메시지 남음", "일부러 실패" in (claimed.error or ""))
db.close()

print("=== 5. redis push 실패해도 표에는 남고, sweep 이 다시 큐에 올린다 ===")
fake.push_should_fail = True
db = SessionLocal()
before = len(fake._list)
job3 = ai_jobs.enqueue(db, UID, "test_echo", {"x": 99})
chk("push 실패해도 표에는 queued 로 남음", job3.status == "queued")
chk("redis 큐에는 실제로 안 들어감(push 실패)", len(fake._list) == before)
db.close()
fake.push_should_fail = False
ai_jobs._redis_sweep_orphans()
chk("sweep 이후 큐에 다시 들어감", str(job3.id).encode() in fake._list, str(fake._list))

print("=== 6. queue_position — 대기 중인 작업 앞에 몇 개 있는지 ===")
db = SessionLocal()
qjob = db.query(AiJob).filter(AiJob.id == job3.id).first()
pos = ai_jobs.queue_position(db, qjob)
chk("대기 중이므로 숫자(0 이상)를 돌려줌", isinstance(pos, int) and pos >= 0, str(pos))
db.close()

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
if sum(OK) != len(OK):
    sys.exit(1)
