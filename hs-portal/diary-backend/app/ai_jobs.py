"""AI 작업을 뒤에서 처리하는 자리.

**왜 뒤로 미루나**

AI 는 몇 초에서 수십 초가 걸린다. 그동안 웹 요청을 붙들고 있으면
gunicorn 워커 하나가 통째로 묶인다. 워커가 두어 개인데 학생 셋이
동시에 누르면 남는 워커가 없고, 그 순간 자소서와 상관없는 다른 학생의
일지 저장까지 멈춘다. AI 기능 하나가 서비스 전체를 막는 셈이다.

그래서 요청을 표에 적어 두고 바로 응답한다. 화면은 몇 초마다
결과가 나왔는지 물어본다.

**백엔드 두 가지 — `AI_QUEUE_BACKEND`**

- `"db"`(기본): 이 프로세스 안에서 스레드 여러 개(`AI_JOB_WORKERS`, 기본 1개)가
  표를 들여다보며 처리한다. gunicorn 워커 수만큼 프로세스가 늘어나고,
  프로세스마다 이 스레드들이 따로 돈다. 지금 규모(트래픽 적음)엔 이걸로 충분하다.
- `"redis"`: 웹서버(gunicorn) 프로세스와 완전히 분리된 별도 프로세스
  (`python -m app.ai_worker`)가 Redis 큐에서 작업을 받아 처리한다. 이 모드를
  쓰면 이 프로세스는 `start()`를 불러도 처리 스레드를 띄우지 않는다 —
  `ai_worker.py`를 원하는 만큼 따로 띄워야 실제로 처리된다. AI 처리량을
  gunicorn 워커 수(=웹 요청 처리 능력)와 완전히 독립적으로 늘릴 수 있다.

작업 상태(대기/처리중/완료, 결과)는 어느 백엔드든 항상 `AiJob` 표에
남는다 — 화면이 폴링하는 `GET /api/ai/jobs/{id}`는 표만 보므로 백엔드를
바꿔도 프론트/API 계약은 그대로다.

**워커가 여러 개일 때(db 백엔드, 스레드든 프로세스든 마찬가지)**

같은 일을 두 번 하지 않도록, 작업을 집어갈 때 queued → running 으로
바꾸고 바뀐 줄 수를 확인한다. 먼저 바꾼 쪽만 그 일을 한다.
"""

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

from .database import SessionLocal
from .models import AiJob

# 일꾼이 얼마나 자주 표를 들여다볼지(초) — db 백엔드에서만 쓰인다.
POLL_SECONDS = 2

# 이 시간이 지나도 안 끝난 작업은 죽은 것으로 본다(분).
# 서버가 중간에 재시작되면 running 인 채로 남는다.
STALE_MINUTES = 10

# 끝난 작업을 며칠 뒤에 치울지
KEEP_DAYS = 3

QUEUE_BACKEND = os.getenv("AI_QUEUE_BACKEND", "db").strip().lower()
# db 백엔드에서 이 프로세스 안에 몇 개의 일꾼 스레드를 둘지.
JOB_WORKERS = max(1, int(os.getenv("AI_JOB_WORKERS", "1")))
REDIS_URL = os.getenv("AI_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
REDIS_QUEUE_KEY = os.getenv("AI_REDIS_QUEUE_KEY", "hsportal:ai_jobs")
# redis 워커가 대기 중인 queued 행(=redis push 가 실패해 표에만 남은 것)을
# 얼마나 자주 다시 큐에 올릴지(초).
REDIS_SWEEP_SECONDS = 30

_workers: list = []
_stop = threading.Event()
_redis_client = None

# 작업 종류별로 실제 일을 하는 함수. main.py 가 등록한다.
# 여기서 main 을 부르면 서로 물고 물려 import 가 꼬인다.
_handlers = {}


def register(kind: str, fn) -> None:
    """작업 종류와 처리 함수를 이어 둔다."""
    _handlers[kind] = fn


def _get_redis():
    """redis 클라이언트를 지연 생성한다 — db 백엔드만 쓰면 redis 패키지가
    없어도 이 함수가 안 불리니 문제없다."""
    global _redis_client
    if _redis_client is None:
        import redis  # noqa: PLC0415 — 지연 import
        _redis_client = redis.from_url(REDIS_URL)
    return _redis_client


def enqueue(db, user_id: int, kind: str, payload: dict, dedup_key: str = None,
           dedup_scope: str = "user") -> AiJob:
    """할 일을 적어 둔다. 바로 돌아온다.

    dedup_key를 주면, 같은 요청(같은 kind+같은 대상)을 연타해도 새로 만들지
    않고 이미 기다리는/도는 중인 작업을 그대로 돌려준다 — 버튼을 두 번 눌러
    같은 AI 요청이 두 번 쌓이는 것을 막는다.

    dedup_scope="user"(기본)면 "같은 사람이" 연타할 때만 합친다 — 자소서
    테마 추천처럼 dedup_key 가 사람마다 안 겹치는 값이 아닐 때 쓴다.
    dedup_scope="any"면 요청한 사람이 달라도 kind+dedup_key 가 같으면
    합친다 — 팀원 여럿이 거의 동시에 "종합" 버튼을 눌러도 하나로 묶이도록,
    dedup_key 자체가 이미 team/research 단위로 고유할 때(팀 게시판 종합 등)
    쓴다.
    """
    if dedup_key:
        q = db.query(AiJob).filter(AiJob.kind == kind, AiJob.dedup_key == dedup_key,
                                   AiJob.status.in_(("queued", "running")))
        if dedup_scope != "any":
            q = q.filter(AiJob.user_id == user_id)
        existing = q.order_by(AiJob.created_at.desc()).first()
        if existing:
            return existing

    job = AiJob(
        user_id=user_id, kind=kind, status="queued", dedup_key=dedup_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if QUEUE_BACKEND == "redis":
        try:
            _get_redis().lpush(REDIS_QUEUE_KEY, str(job.id))
        except Exception as exc:
            # 못 넣어도 표에는 queued 로 남아 있다 — ai_worker.py 의 주기적
            # 정리(_redis_sweep_orphans)가 나중에 다시 큐에 올린다.
            print(f"[AI작업] redis 전달 실패(나중에 재시도됨): {type(exc).__name__}", flush=True)

    return job


def queue_position(db, job: AiJob) -> Optional[int]:
    """이 작업 앞에 몇 개가 더 기다리고 있는지. 대기 중이 아니면 None."""
    if job.status != "queued":
        return None
    return db.query(AiJob).filter(
        AiJob.status == "queued", AiJob.created_at < job.created_at).count()


def job_out(job: AiJob, db=None) -> dict:
    """화면에 내려줄 모양. db 를 주면 대기 중일 때 앞에 몇 명이 더 있는지도 담는다."""
    try:
        result = json.loads(job.result_json or "{}")
    except (ValueError, TypeError):
        result = {}
    out = {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result": result,
        "error": job.error or "",
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }
    if db is not None and job.status == "queued":
        out["queue_position"] = queue_position(db, job)
    return out


def _execute(db, job: AiJob) -> None:
    """이미 running 으로 바뀐 작업 하나를 실제로 처리하고 결과를 표에 남긴다.

    db 백엔드(스레드)든 redis 백엔드(별도 프로세스)든 이 함수 하나를
    같이 쓴다 — 처리 로직이 두 곳에서 따로 놀며 갈라지는 것을 막는다.
    """
    handler = _handlers.get(job.kind)
    if handler is None:
        job.status = "failed"
        job.error = "처리할 수 없는 요청입니다."
        job.finished_at = datetime.utcnow()
        db.commit()
        return

    try:
        payload = json.loads(job.payload_json or "{}")
    except (ValueError, TypeError):
        payload = {}

    try:
        result = handler(db, job.user_id, payload) or {}
        if result.get("ok"):
            job.status = "done"
            job.result_json = json.dumps(result, ensure_ascii=False, default=str)
        else:
            job.status = "failed"
            job.error = str(result.get("error") or "처리하지 못했습니다.")[:300]
    except Exception as exc:
        # 일꾼이 죽으면 다음 작업도 못 한다. 어떤 오류든 여기서 잡는다.
        # 오류 메시지에 글 내용이 섞일 수 있어 갈래만 로그에 남긴다.
        print(f"[AI작업] id={job.id} kind={job.kind} 실패: "
              f"{type(exc).__name__}", flush=True)
        traceback.print_exc()
        job.status = "failed"
        job.error = "처리 중 문제가 생겼습니다. 다시 시도해주세요."

    job.finished_at = datetime.utcnow()
    db.commit()


def _take_one(db) -> Optional[AiJob]:
    """기다리는 작업 하나를 집어 온다(가장 오래된 것부터).

    워커가 여럿일 때 같은 작업을 두 번 하지 않도록, 상태를 바꾼
    줄 수를 확인한다. 먼저 바꾼 쪽만 가져간다.
    """
    job = (db.query(AiJob)
           .filter(AiJob.status == "queued")
           .order_by(AiJob.created_at).first())
    if job is None:
        return None
    return _claim(db, job.id)


def _claim(db, job_id: int) -> Optional[AiJob]:
    """특정 id 의 queued 작업을 running 으로 바꾸며 가져간다.
    이미 다른 워커가 가져갔으면 None."""
    changed = (db.query(AiJob)
               .filter(AiJob.id == job_id, AiJob.status == "queued")
               .update({"status": "running", "started_at": datetime.utcnow()},
                       synchronize_session=False))
    db.commit()
    if not changed:
        return None
    return db.query(AiJob).filter(AiJob.id == job_id).first()


def _run_once() -> bool:
    """(db 백엔드) 작업 하나를 처리한다. 처리했으면 True."""
    db = SessionLocal()
    try:
        job = _take_one(db)
        if job is None:
            return False
        _execute(db, job)
        return True
    finally:
        db.close()


def _cleanup() -> None:
    """멈춰 있는 작업을 정리하고, 오래된 것을 치운다."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # 서버가 중간에 재시작되면 running 인 채로 남는다. 실패로 돌린다.
        db.query(AiJob).filter(
            AiJob.status == "running",
            AiJob.started_at < now - timedelta(minutes=STALE_MINUTES),
        ).update({"status": "failed",
                  "error": "처리가 중단되었습니다. 다시 시도해주세요.",
                  "finished_at": now}, synchronize_session=False)

        db.query(AiJob).filter(
            AiJob.created_at < now - timedelta(days=KEEP_DAYS)
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[AI작업] 정리 실패: {type(exc).__name__}", flush=True)
    finally:
        db.close()


def _loop() -> None:
    """(db 백엔드) 일꾼 스레드 하나의 반복문. 여러 스레드가 이 함수를 같이 돈다."""
    last_cleanup = 0.0
    while not _stop.is_set():
        try:
            worked = _run_once()
        except Exception as exc:
            # 여기서 죽으면 일꾼이 사라진다. 무슨 일이 있어도 계속 돈다.
            print(f"[AI작업] 일꾼 오류: {type(exc).__name__}", flush=True)
            worked = False

        now = time.time()
        if now - last_cleanup > 300:
            _cleanup()
            last_cleanup = now

        if not worked:
            _stop.wait(POLL_SECONDS)


def start(count: Optional[int] = None) -> None:
    """일꾼을 띄운다. 여러 번 불러도 정해진 개수만 돈다.

    redis 백엔드면 아무것도 안 한다 — 처리는 별도로 띄운
    `python -m app.ai_worker` 프로세스가 담당한다.

    daemon 스레드로 두어 서버를 내릴 때 붙잡지 않게 한다.
    """
    if QUEUE_BACKEND == "redis":
        print("[AI작업] AI_QUEUE_BACKEND=redis — 이 프로세스는 처리 스레드를 띄우지 않습니다. "
              "`python -m app.ai_worker` 를 별도로 실행해야 작업이 처리됩니다.", flush=True)
        return

    global _workers
    if _workers and any(w.is_alive() for w in _workers):
        return
    n = count if count is not None else JOB_WORKERS
    n = max(1, n)
    _stop.clear()
    _workers = []
    for i in range(n):
        t = threading.Thread(target=_loop, name=f"ai-jobs-{i}", daemon=True)
        t.start()
        _workers.append(t)
    print(f"[AI작업] 일꾼 {n}개 시작", flush=True)


def stop() -> None:
    _stop.set()


# ── redis 백엔드 전용 — ai_worker.py 가 부른다 ──────────────────

def _redis_sweep_orphans() -> None:
    """redis push 가 실패해 표에만 queued 로 남은 작업을 다시 큐에 올린다."""
    db = SessionLocal()
    try:
        ids = [jid for (jid,) in db.query(AiJob.id).filter(AiJob.status == "queued").all()]
    finally:
        db.close()
    if not ids:
        return
    r = _get_redis()
    for jid in ids:
        r.lpush(REDIS_QUEUE_KEY, str(jid))


def run_redis_worker_forever() -> None:
    """redis 큐에서 작업 id 를 받아 처리하는 전용 워커 프로세스의 반복문.
    Ctrl-C(SIGINT) 등으로만 멈춘다 — 별도 프로세스이므로 `_stop` 이벤트와는 무관하다."""
    r = _get_redis()
    last_sweep = 0.0
    last_cleanup = 0.0
    while True:
        try:
            item = r.brpop(REDIS_QUEUE_KEY, timeout=5)
            if item:
                _, job_id_raw = item
                job_id = int(job_id_raw)
                db = SessionLocal()
                try:
                    job = _claim(db, job_id)
                    if job is not None:
                        _execute(db, job)
                finally:
                    db.close()

            now = time.time()
            if now - last_sweep > REDIS_SWEEP_SECONDS:
                _redis_sweep_orphans()
                last_sweep = now
            if now - last_cleanup > 300:
                _cleanup()
                last_cleanup = now
        except Exception as exc:
            print(f"[AI워커] 오류: {type(exc).__name__}", flush=True)
            time.sleep(2)
