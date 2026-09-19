"""Fixed-window rate limiting.

Redis-backed in every deployed environment; the in-memory implementation exists for
tests and single-process tooling only. If Redis is unreachable the limiter fails open
(availability over strictness) and logs a warning — auth still requires valid credentials.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.requests import Request

from app.core.errors import RateLimited

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_s: int


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_s: int) -> RateLimitDecision: ...


def _window(now: float, window_s: int) -> tuple[int, int]:
    bucket = math.floor(now / window_s)
    retry_after = max(1, math.ceil((bucket + 1) * window_s - now))
    return bucket, retry_after


class RedisRateLimiter:
    def __init__(self, redis: Redis, *, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    async def hit(self, key: str, *, limit: int, window_s: int) -> RateLimitDecision:
        bucket, retry_after = _window(self._clock(), window_s)
        redis_key = f"rl:{key}:{bucket}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_s + 1)
                count, _ = await pipe.execute()
        except (RedisError, OSError, TimeoutError):
            logger.warning("rate_limiter_unavailable", extra={"limiter_scope": key.split(":", 1)[0]})
            return RateLimitDecision(allowed=True, remaining=limit, retry_after_s=0)
        count = int(count)
        return RateLimitDecision(
            allowed=count <= limit, remaining=max(0, limit - count), retry_after_s=retry_after
        )


class InMemoryRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, *, limit: int, window_s: int) -> RateLimitDecision:
        bucket, retry_after = _window(self._clock(), window_s)
        bucket_key = f"{key}:{bucket}"
        async with self._lock:
            count = self._counts.get(bucket_key, 0) + 1
            self._counts[bucket_key] = count
        return RateLimitDecision(
            allowed=count <= limit, remaining=max(0, limit - count), retry_after_s=retry_after
        )


async def enforce(limiter: RateLimiter, key: str, *, limit: int, window_s: int) -> None:
    decision = await limiter.hit(key, limit=limit, window_s=window_s)
    if not decision.allowed:
        raise RateLimited(decision.retry_after_s)


def client_ip(request: Request, trusted_proxy_count: int) -> str:
    """Client address, trusting X-Forwarded-For only for the configured number of proxy hops."""
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= trusted_proxy_count:
            return hops[-trusted_proxy_count]
    return request.client.host if request.client else "unknown"
