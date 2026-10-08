"""Timeout and retry wrappers shared by every provider (docs/provider-abstraction.md §4).

A provider implementation handles one request; this decides how long it may take and when it may be tried
again. Two rules are load-bearing:

* only ``ProviderError.retryable`` failures are retried — a bad request or rejected credentials would come
  back identical, and retrying them just multiplies the bill;
* a **stream is retried only before its first chunk**. Re-running a half-spoken answer would play the
  beginning twice to the user (and bill twice), so once text is out we fail forward.
"""

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

from story_core.providers.base import ProviderError, ProviderInfo, ProviderRateLimited
from story_core.providers.embedding.base import EmbeddingKind, EmbeddingProvider, EmbeddingResult
from story_core.providers.llm.base import LLMChunk, LLMProvider, LLMRequest, LLMResponse, close_stream

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_s: float = 0.2
    max_delay_s: float = 4.0
    jitter: bool = True

    def delay_for(self, attempt: int, *, retry_after_s: float | None = None) -> float:
        """Exponential backoff with full jitter; a provider's own Retry-After wins."""
        if retry_after_s is not None:
            return min(retry_after_s, self.max_delay_s)
        ceiling = min(self.base_delay_s * (2**attempt), self.max_delay_s)
        return random.uniform(0, ceiling) if self.jitter else ceiling  # noqa: S311 - backoff, not crypto


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Defaults from docs/provider-abstraction.md §4; realtime callers pass shorter ones."""

    llm_total_s: float = 30.0
    llm_first_token_s: float = 5.0
    embedding_s: float = 10.0


async def call_with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    tag: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    last: ProviderError | None = None
    for attempt in range(policy.attempts):
        try:
            return await operation()
        except ProviderError as exc:
            if not exc.retryable or attempt == policy.attempts - 1:
                raise
            last = exc
            retry_after = exc.retry_after_s if isinstance(exc, ProviderRateLimited) else None
            delay = policy.delay_for(attempt, retry_after_s=retry_after)
            logger.warning(
                "provider_retry",
                extra={"tag": tag, "attempt": attempt + 1, "error_type": type(exc).__name__},
            )
            await sleep(delay)
    raise last if last else ProviderError("retry loop did not run")


class ResilientLLMProvider:
    """Applies the configured timeout and retry policy to an LLMProvider."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        policy: RetryPolicy | None = None,
        timeouts: Timeouts | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._timeouts = timeouts or Timeouts()
        self._sleep = sleep
        self.info: ProviderInfo = inner.info

    async def generate(self, request: LLMRequest, *, timeout_s: float | None = None) -> LLMResponse:
        budget = timeout_s or self._timeouts.llm_total_s
        return await call_with_retry(
            lambda: self._inner.generate(request, timeout_s=budget),
            policy=self._policy,
            tag=f"llm:{request.request_tag}",
            sleep=self._sleep,
        )

    async def stream(self, request: LLMRequest, *, timeout_s: float | None = None) -> AsyncIterator[LLMChunk]:
        budget = timeout_s or self._timeouts.llm_total_s
        attempt = 0
        while True:
            stream = self._inner.stream(request, timeout_s=budget)
            try:
                first = await anext(stream)
            except StopAsyncIteration:
                return
            except ProviderError as exc:
                await close_stream(stream)
                if not exc.retryable or attempt >= self._policy.attempts - 1:
                    raise
                retry_after = exc.retry_after_s if isinstance(exc, ProviderRateLimited) else None
                await self._sleep(self._policy.delay_for(attempt, retry_after_s=retry_after))
                attempt += 1
                continue
            # First chunk is out: from here a failure is surfaced, never replayed.
            try:
                yield first
                async for chunk in stream:
                    yield chunk
            finally:
                await close_stream(stream)
            return


class ResilientEmbeddingProvider:
    def __init__(
        self,
        inner: EmbeddingProvider,
        *,
        policy: RetryPolicy | None = None,
        timeouts: Timeouts | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._timeouts = timeouts or Timeouts()
        self._sleep = sleep
        self.info: ProviderInfo = inner.info
        self.dimensions: int = inner.dimensions

    async def embed(
        self, texts: Sequence[str], *, kind: EmbeddingKind, timeout_s: float | None = None
    ) -> EmbeddingResult:
        budget = timeout_s or self._timeouts.embedding_s
        return await call_with_retry(
            lambda: self._inner.embed(texts, kind=kind, timeout_s=budget),
            policy=self._policy,
            tag=f"embedding:{kind}",
            sleep=self._sleep,
        )
