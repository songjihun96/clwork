"""IntentRouter: rules, then a small model, then a safe default (docs/ai-architecture.md §2.2).

The model is asked only when the rules decline, and it is given a hard budget: one short call with guided
decoding. If it is slow, unavailable or answers with something outside the enum, the router falls back to
``BOOK_QUESTION`` — a question answered from the book is recoverable, a wrongly-stopped narration is not.
"""

import asyncio
import logging

from story_core.agent.intent import (
    CLASSIFIER_PROMPT,
    INTENT_SCHEMA,
    IntentDecision,
    classify_by_rule,
    parse_classifier_output,
)
from story_core.providers.base import ProviderError
from story_core.providers.llm.base import ChatMessage, LLMProvider, LLMRequest
from story_core.reading.state_machine import Intent, ReadingState

logger = logging.getLogger(__name__)

# The realtime budget: the user is waiting in silence while this runs.
CLASSIFIER_TIMEOUT_S = 0.15
CLASSIFIER_MAX_TOKENS = 16


class IntentRouter:
    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        timeout_s: float = CLASSIFIER_TIMEOUT_S,
        fallback: Intent = Intent.BOOK_QUESTION,
    ) -> None:
        self._llm = llm
        self._timeout_s = timeout_s
        self._fallback = fallback
        # Diagnostics for the eval script: how often each layer decided.
        self.rule_hits = 0
        self.llm_hits = 0
        self.fallbacks = 0

    async def route(self, text: str, state: ReadingState) -> IntentDecision:
        decided = classify_by_rule(text, state)
        if decided is not None:
            self.rule_hits += 1
            return decided
        if self._llm is None:
            self.fallbacks += 1
            return IntentDecision(self._fallback, source="fallback", confidence=0.5)

        request = LLMRequest(
            messages=[
                ChatMessage(role="system", content=CLASSIFIER_PROMPT),
                ChatMessage(role="user", content=text),
            ],
            max_tokens=CLASSIFIER_MAX_TOKENS,
            request_tag="intent",
            temperature=0.0,
            json_schema=INTENT_SCHEMA if "json_schema" in self._llm.info.capabilities else None,
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                response = await self._llm.generate(request, timeout_s=self._timeout_s)
        except (TimeoutError, ProviderError) as exc:
            logger.warning("intent_classifier_unavailable", extra={"error_type": type(exc).__name__})
            self.fallbacks += 1
            return IntentDecision(self._fallback, source="fallback", confidence=0.5)

        intent = parse_classifier_output(response.text)
        if intent is None:
            logger.warning("intent_classifier_bad_output")
            self.fallbacks += 1
            return IntentDecision(self._fallback, source="fallback", confidence=0.5)
        self.llm_hits += 1
        return IntentDecision(intent, source="llm", confidence=0.8)
