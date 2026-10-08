"""LLMProvider for any OpenAI-compatible `/chat/completions` endpoint (hosted or self-hosted vLLM).

``max_tokens`` (not ``max_completion_tokens``) is sent because vLLM and most compatible servers accept it;
a vendor that only takes the newer name needs its own thin adapter, which is the point of the interface.
"""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from story_core.providers.base import ProviderBadRequest, ProviderInfo, ProviderUnavailable, Usage
from story_core.providers.http import (
    HttpProviderConfig,
    build_client,
    decode_json,
    raise_for_status,
    wrap_transport_error,
)
from story_core.providers.llm.base import ChatMessage, LLMChunk, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

_DONE = "[DONE]"


def _messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _usage(payload: dict[str, Any] | None) -> Usage | None:
    if not payload:
        return None
    return Usage(
        input_tokens=int(payload.get("prompt_tokens", 0) or 0),
        output_tokens=int(payload.get("completion_tokens", 0) or 0),
    )


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        config: HttpProviderConfig,
        *,
        capabilities: frozenset[str] = frozenset({"streaming"}),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or build_client(config)
        self._owns_client = client is None
        self.info = ProviderInfo(provider="openai_compatible", model=config.model, capabilities=capabilities)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        if request.json_schema is not None and "json_schema" not in self.info.capabilities:
            raise ProviderBadRequest(f"{self.info.model} does not support structured output")
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": _messages(request.messages),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        if request.json_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": request.json_schema}
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def generate(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        # Built outside the try: a rejected request must stay ProviderBadRequest (never retried), not be
        # re-wrapped as a retryable transport failure.
        payload = self._payload(request, stream=False)
        try:
            response = await self._client.post(
                self._config.endpoint("chat/completions"), json=payload, timeout=timeout_s
            )
            body = response.content
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc) from exc
        raise_for_status(response, body)
        data = decode_json(body)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderUnavailable("chat completion had no choices")
        message = choices[0].get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ProviderUnavailable("chat completion had no text content")
        return LLMResponse(
            text=text,
            usage=_usage(data.get("usage")) or Usage(),
            finish_reason=choices[0].get("finish_reason"),
        )

    async def stream(self, request: LLMRequest, *, timeout_s: float) -> AsyncIterator[LLMChunk]:
        """Server-sent events. Closing the iterator (cancel, ``aclose``) closes the upstream connection,
        which is what stops a cancelled barge-in answer from billing to the end."""
        payload = self._payload(request, stream=True)
        try:
            async with self._client.stream(
                "POST", self._config.endpoint("chat/completions"), json=payload, timeout=timeout_s
            ) as response:
                if response.status_code >= 400:
                    raise_for_status(response, await response.aread())
                async for line in response.aiter_lines():
                    chunk = _parse_sse_line(line)
                    if isinstance(chunk, _StreamEnd):
                        return
                    if chunk is not None:
                        yield chunk
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc) from exc


class _StreamEnd:
    pass


_STREAM_END = _StreamEnd()


def _parse_sse_line(line: str) -> LLMChunk | _StreamEnd | None:
    """One SSE line → a chunk, the end marker, or None for keep-alives and comments."""
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data:
        return None
    if data == _DONE:
        return _STREAM_END
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("llm_stream_bad_chunk")
        return None
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    usage = _usage(payload.get("usage"))
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        # A usage-only final frame (stream_options.include_usage) carries no choices.
        return LLMChunk(delta="", usage=usage) if usage else None
    choice = choices[0]
    delta = choice.get("delta")
    text = delta.get("content") if isinstance(delta, dict) else None
    finish = choice.get("finish_reason")
    if not isinstance(text, str) and finish is None and usage is None:
        return None
    return LLMChunk(delta=text if isinstance(text, str) else "", finish_reason=finish, usage=usage)
