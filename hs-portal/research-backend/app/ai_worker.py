"""AI 작업 전담 워커 프로세스 — `AI_QUEUE_BACKEND=redis` 일 때만 쓴다.

웹서버(gunicorn) 프로세스와 완전히 분리해서, 이 프로세스만 원하는 만큼
따로 띄워 AI 처리량을 독립적으로 늘릴 수 있다(웹 요청 처리 능력과 무관).
DB 폴링 방식(`AI_JOB_WORKERS`)과 달리 Redis 큐에서 작업 id 를 즉시
받아 오므로 대기 지연도 더 짧다.

실행:
    python -m app.ai_worker

여러 개 띄우면 그만큼 병렬로 처리된다 — Redis 리스트의 BRPOP 은 여러
소비자가 붙어도 각 항목이 정확히 하나에게만 간다. 같은 서버에 여러 개를
띄워도 되고, 완전히 다른 서버에 띄워도 된다(REDIS_URL 로 같은 Redis만
바라보면 됨).
"""
import sys

from . import ai_jobs
# main 을 import 해야 ai_jobs.register(...) 로 등록되는 작업 처리 함수들이
# 실제로 등록된다(등록은 main.py 로드 시점에 일어난다).
from . import main  # noqa: F401


def run() -> None:
    if ai_jobs.QUEUE_BACKEND != "redis":
        print("[AI워커] AI_QUEUE_BACKEND=redis 로 설정돼 있지 않습니다. "
              "지금 설정으로는 이 프로세스가 할 일이 없습니다(.env 확인 필요).",
              flush=True)
        sys.exit(1)
    print(f"[AI워커] 시작 — redis={ai_jobs.REDIS_URL} "
          f"queue={ai_jobs.REDIS_QUEUE_KEY}", flush=True)
    ai_jobs.run_redis_worker_forever()


if __name__ == "__main__":
    run()
