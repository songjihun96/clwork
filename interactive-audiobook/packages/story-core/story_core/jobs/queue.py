"""Background job abstraction.

Services enqueue by task *name*, so the API never imports worker code. Taskiq with a Redis Streams
broker gives at-least-once delivery (messages are acknowledged after the task runs), therefore every
task must be idempotent. Enqueueing is not transactional with PostgreSQL: the book row records
``queued`` first, and a stale ``queued`` book can simply be enqueued again.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from taskiq import AsyncBroker, SmartRetryMiddleware
from taskiq.kicker import AsyncKicker
from taskiq_redis import RedisStreamBroker

INGEST_BOOK_TASK = "books.ingest"
EMBED_BOOK_TASK = "books.embed"
RENDER_PARAGRAPH_AUDIO_TASK = "audio.render_paragraph"
QUEUE_NAME = "audiobook:jobs"


class JobQueue(Protocol):
    async def enqueue(self, task_name: str, **kwargs: Any) -> None: ...


def create_broker(redis_url: str) -> RedisStreamBroker:
    broker = RedisStreamBroker(
        redis_url,
        queue_name=QUEUE_NAME,
        consumer_group_name="audiobook-workers",
        # Re-deliver messages whose worker died mid-task.
        unacknowledged_lock_timeout=15 * 60,
        idle_timeout=15 * 60 * 1000,
    )
    return broker.with_middlewares(
        SmartRetryMiddleware(default_retry_count=3, default_delay=5, use_jitter=True, use_delay_exponent=True)
    )


class TaskiqJobQueue:
    def __init__(self, broker: AsyncBroker) -> None:
        self._broker = broker

    async def enqueue(self, task_name: str, **kwargs: Any) -> None:
        await AsyncKicker(task_name=task_name, broker=self._broker, labels={}).kiq(**kwargs)


@dataclass
class RecordingJobQueue:
    """Test double: records jobs so tests can run them explicitly."""

    jobs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def enqueue(self, task_name: str, **kwargs: Any) -> None:
        self.jobs.append((task_name, kwargs))
