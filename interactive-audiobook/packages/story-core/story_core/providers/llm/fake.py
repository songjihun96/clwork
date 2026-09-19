"""Offline LLM provider for development and tests.

It is a stub, not a model: by default it answers from the ``<context>`` block it was given and refuses
when that block is empty. That makes the *plumbing* of grounded answering testable without a vendor —
retrieval, budget, spoiler guard, persistence — while the real answer quality and refusal rate can only
be measured with a real model (docs/roadmap.md Phase 4). Rejected in production settings.
"""

import asyncio
import re
from collections import deque
from collections.abc import AsyncIterator, Iterable, Sequence

from story_core.providers.base import ProviderError, ProviderInfo, Usage
from story_core.providers.llm.base import LLMChunk, LLMRequest, LLMResponse

# Matches the context block built by story_core.rag.context.
_CONTEXT = re.compile(r"<context>(.*?)</context>", re.DOTALL)
NO_CONTEXT_ANSWER = "책에서 그 내용을 찾지 못했어요."
_CHUNK_SIZE = 12


def context_of(request: LLMRequest) -> str:
    for message in request.messages:
        found = _CONTEXT.search(message.content)
        if found:
            return found.group(1).strip()
    return ""


class FakeLLMProvider:
    """``responses`` are handed out in order, then the default behaviour resumes.

    ``failures`` raise instead of answering (retry and circuit-breaker tests); ``chunk_delay_s`` slows the
    stream so a test can cancel mid-answer.
    """

    def __init__(
        self,
        *,
        responses: Sequence[str] = (),
        failures: Iterable[ProviderError] = (),
        model: str = "fake-story-v1",
        chunk_delay_s: float = 0.0,
        capabilities: frozenset[str] = frozenset({"streaming", "json_schema"}),
    ) -> None:
        self.info = ProviderInfo(provider="fake", model=model, capabilities=capabilities)
        self._responses = deque(responses)
        self._failures = deque(failures)
        self._chunk_delay_s = chunk_delay_s
        self.requests: list[LLMRequest] = []
        # True once a stream was closed before finishing: asserts cancellation reached the provider.
        self.cancelled = False
        self.completed_streams = 0

    def answer_for(self, request: LLMRequest) -> str:
        if self._responses:
            return self._responses.popleft()
        context = context_of(request)
        if not context:
            return NO_CONTEXT_ANSWER
        # Echo the most relevant retrieved line: grounded by construction, so a leaked line is visible.
        first = next((line.strip() for line in context.splitlines() if line.strip()), "")
        return first[:200]

    def _check_failure(self) -> None:
        if self._failures:
            raise self._failures.popleft()

    async def generate(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        self.requests.append(request)
        self._check_failure()
        text = self.answer_for(request)
        return LLMResponse(text=text, usage=_usage(request, text), finish_reason="stop")

    async def stream(self, request: LLMRequest, *, timeout_s: float) -> AsyncIterator[LLMChunk]:
        self.requests.append(request)
        self._check_failure()
        text = self.answer_for(request)
        pieces = [text[i : i + _CHUNK_SIZE] for i in range(0, len(text), _CHUNK_SIZE)] or [""]
        finished = False
        try:
            for piece in pieces:
                if self._chunk_delay_s:
                    await asyncio.sleep(self._chunk_delay_s)
                yield LLMChunk(delta=piece)
            finished = True
            yield LLMChunk(delta="", finish_reason="stop", usage=_usage(request, text))
            self.completed_streams += 1
        finally:
            if not finished:
                self.cancelled = True


def _usage(request: LLMRequest, text: str) -> Usage:
    prompt_chars = sum(len(message.content) for message in request.messages)
    return Usage(input_tokens=prompt_chars // 3, output_tokens=max(len(text) // 3, 1))
