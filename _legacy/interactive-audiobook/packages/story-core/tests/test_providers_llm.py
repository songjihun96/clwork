"""LLM/embedding provider contract: error mapping, retry rules, SSE streaming, cancellation.

The OpenAI-compatible providers are exercised through httpx's MockTransport (no network, real client
code path) plus one real socket server for the cancellation contract, which is the only way to prove the
upstream connection actually closes (docs/provider-abstraction.md §5).
"""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from story_core.providers.base import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from story_core.providers.embedding.fake import FakeEmbeddingProvider
from story_core.providers.embedding.openai_compatible import OpenAICompatibleEmbeddingProvider
from story_core.providers.http import HttpProviderConfig
from story_core.providers.llm.base import ChatMessage, LLMRequest
from story_core.providers.llm.fake import NO_CONTEXT_ANSWER, FakeLLMProvider
from story_core.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from story_core.providers.resilience import (
    ResilientEmbeddingProvider,
    ResilientLLMProvider,
    RetryPolicy,
    call_with_retry,
)

CONFIG = HttpProviderConfig(base_url="https://llm.test/v1", model="test-model", api_key="secret")
REQUEST = LLMRequest(
    messages=[ChatMessage(role="user", content="모모는 누구야?")], max_tokens=64, request_tag="story_answer"
)


def llm(handler: object) -> OpenAICompatibleLLMProvider:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return OpenAICompatibleLLMProvider(
        CONFIG, client=httpx.AsyncClient(transport=transport, headers={"Authorization": "Bearer secret"})
    )


def completion(text: str, *, finish: str = "stop") -> dict[str, object]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


async def test_generate_sends_openai_payload_and_maps_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=completion("모모는 주인공이야."))

    response = await llm(handler).generate(REQUEST, timeout_s=5)

    assert response.text == "모모는 주인공이야."
    assert response.usage.input_tokens == 11 and response.usage.output_tokens == 7
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["model"] == "test-model" and seen["max_tokens"] == 64
    assert seen["messages"] == [{"role": "user", "content": "모모는 누구야?"}]
    assert seen["auth"] == "Bearer secret"
    assert "stream" not in seen


@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (401, ProviderAuthError, False),
        (403, ProviderAuthError, False),
        (400, ProviderBadRequest, False),
        (429, ProviderRateLimited, True),
        (500, ProviderUnavailable, True),
        (503, ProviderUnavailable, True),
        (504, ProviderTimeout, True),
    ],
)
async def test_http_status_maps_to_provider_error(
    status: int, expected: type[Exception], retryable: bool
) -> None:
    provider = llm(lambda request: httpx.Response(status, json={"error": {"code": "boom"}}))

    with pytest.raises(expected) as caught:
        await provider.generate(REQUEST, timeout_s=5)
    assert getattr(caught.value, "retryable", False) is retryable


async def test_rate_limit_keeps_retry_after() -> None:
    provider = llm(lambda request: httpx.Response(429, headers={"retry-after": "2.5"}, json={}))

    with pytest.raises(ProviderRateLimited) as caught:
        await provider.generate(REQUEST, timeout_s=5)
    assert caught.value.retry_after_s == 2.5


async def test_transport_timeout_becomes_provider_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ProviderTimeout):
        await llm(handler).generate(REQUEST, timeout_s=5)


async def test_error_body_is_not_echoed_in_full() -> None:
    """Provider errors may quote a code, never the prompt that was sent."""
    secret = "책 원문 문장이 그대로 들어간 프롬프트" * 20
    provider = llm(lambda request: httpx.Response(400, json={"error": {"message": secret}}))

    with pytest.raises(ProviderBadRequest) as caught:
        await provider.generate(REQUEST, timeout_s=5)
    assert len(str(caught.value)) < 300


async def test_json_schema_requires_the_capability() -> None:
    schema: dict[str, object] = {"name": "intent", "schema": {"type": "object"}}
    request = LLMRequest(messages=REQUEST.messages, max_tokens=16, request_tag="intent", json_schema=schema)
    without = llm(lambda r: httpx.Response(200, json=completion("{}")))

    with pytest.raises(ProviderBadRequest):
        await without.generate(request, timeout_s=5)

    seen: dict[str, object] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return httpx.Response(200, json=completion("{}"))

    provider = OpenAICompatibleLLMProvider(
        CONFIG,
        capabilities=frozenset({"streaming", "json_schema"}),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.generate(request, timeout_s=5)
    assert seen["response_format"] == {"type": "json_schema", "json_schema": schema}


def sse(*frames: dict[str, object] | str) -> bytes:
    lines = []
    for frame in frames:
        payload = frame if isinstance(frame, str) else json.dumps(frame)
        lines.append(f"data: {payload}\n\n")
    return "".join(lines).encode()


async def test_stream_parses_sse_and_final_usage() -> None:
    frames = sse(
        {"choices": [{"delta": {"content": "모모는 "}}]},
        ": keep-alive",
        {"choices": [{"delta": {"content": "주인공이야."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 5}},
        "[DONE]",
    )
    provider = llm(lambda request: httpx.Response(200, content=frames))

    chunks = [chunk async for chunk in provider.stream(REQUEST, timeout_s=5)]

    assert "".join(c.delta for c in chunks) == "모모는 주인공이야."
    assert chunks[-1].usage is not None and chunks[-1].usage.output_tokens == 5
    assert any(c.finish_reason == "stop" for c in chunks)


async def test_stream_error_status_maps_before_any_chunk() -> None:
    provider = llm(lambda request: httpx.Response(503, json={"error": {"code": "overloaded"}}))

    with pytest.raises(ProviderUnavailable):
        _ = [chunk async for chunk in provider.stream(REQUEST, timeout_s=5)]


async def test_retry_only_for_retryable_errors() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderUnavailable("try again")
        return "ok"

    policy = RetryPolicy(attempts=3, base_delay_s=0.1, jitter=False)
    assert await call_with_retry(flaky, policy=policy, tag="t", sleep=sleep) == "ok"
    assert calls["n"] == 3 and delays == [0.1, 0.2]

    async def rejected() -> str:
        calls["n"] += 1
        raise ProviderBadRequest("no")

    with pytest.raises(ProviderBadRequest):
        await call_with_retry(rejected, policy=policy, tag="t", sleep=sleep)
    assert calls["n"] == 4  # called once, never retried


async def test_retry_after_overrides_backoff() -> None:
    delays: list[float] = []
    policy = RetryPolicy(attempts=2, base_delay_s=0.1, max_delay_s=4.0, jitter=False)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    first = {"done": False}

    async def limited() -> str:
        if not first["done"]:
            first["done"] = True
            raise ProviderRateLimited("slow down", retry_after_s=1.5)
        return "ok"

    assert await call_with_retry(limited, policy=policy, tag="t", sleep=sleep) == "ok"
    assert delays == [1.5]


async def test_resilient_stream_retries_before_first_chunk_only() -> None:
    attempts = {"n": 0}

    class Flaky:
        info = FakeLLMProvider().info

        async def generate(self, request: LLMRequest, *, timeout_s: float) -> object:  # pragma: no cover
            raise AssertionError("not used")

        async def stream(self, request: LLMRequest, *, timeout_s: float) -> AsyncIterator[object]:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ProviderUnavailable("dead before first token")
            yield_one = attempts["n"] == 2
            if yield_one:
                from story_core.providers.llm.base import LLMChunk

                yield LLMChunk(delta="첫 토큰")
                raise ProviderUnavailable("died mid-answer")

    async def sleep(delay: float) -> None:
        return None

    provider = ResilientLLMProvider(
        Flaky(),  # type: ignore[arg-type]
        policy=RetryPolicy(attempts=3, base_delay_s=0, jitter=False),
        sleep=sleep,
    )
    seen: list[str] = []
    with pytest.raises(ProviderUnavailable, match="mid-answer"):
        async for chunk in provider.stream(REQUEST):
            seen.append(chunk.delta)

    assert seen == ["첫 토큰"]  # partial answer kept, never replayed
    assert attempts["n"] == 2


async def test_fake_llm_refuses_without_context_and_reports_cancellation() -> None:
    provider = FakeLLMProvider(chunk_delay_s=0.05)
    empty = LLMRequest(
        messages=[ChatMessage(role="system", content="<context>\n</context>")],
        max_tokens=64,
        request_tag="story_answer",
    )
    assert (await provider.generate(empty, timeout_s=1)).text == NO_CONTEXT_ANSWER

    grounded = LLMRequest(
        messages=[ChatMessage(role="system", content="<context>\n모모가 등대에 올랐다.\n</context>")],
        max_tokens=64,
        request_tag="story_answer",
    )
    stream = provider.stream(grounded, timeout_s=1)
    assert (await anext(stream)).delta
    await stream.aclose()  # type: ignore[attr-defined]
    assert provider.cancelled and provider.completed_streams == 0


async def test_embedding_provider_orders_by_index_and_validates_width() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["input"] == ["질문: 하나", "질문: 둘"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 4},
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        HttpProviderConfig(base_url="https://emb.test/v1", model="emb"),
        dimensions=4,
        prefixes={"query": "질문: ", "document": ""},
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.embed(["하나", "둘"], kind="query", timeout_s=5)
    assert result.vectors[0][0] == 1.0 and result.vectors[1][1] == 1.0

    def four_dims(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]}]})

    narrow = OpenAICompatibleEmbeddingProvider(
        HttpProviderConfig(base_url="https://emb.test/v1", model="emb"),
        dimensions=8,
        client=httpx.AsyncClient(transport=httpx.MockTransport(four_dims)),
    )
    with pytest.raises(ProviderUnavailable, match="width"):
        await narrow.embed(["하나"], kind="query", timeout_s=5)


async def test_resilient_embedding_retries_and_keeps_dimensions() -> None:
    inner = FakeEmbeddingProvider(dimensions=16)
    provider = ResilientEmbeddingProvider(inner, policy=RetryPolicy(attempts=2, jitter=False))
    result = await provider.embed(["문장"], kind="document")
    assert provider.dimensions == 16 and len(result.vectors[0]) == 16


async def test_fake_embedding_is_deterministic_and_lexically_meaningful() -> None:
    provider = FakeEmbeddingProvider(dimensions=256)

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    lighthouse = provider.vector("등대지기는 밤마다 불을 켰다")
    same = provider.vector("등대지기는 밤마다 불을 켰다")
    related = provider.vector("등대지기가 등대에 불을 켠다")
    unrelated = provider.vector("도시의 지하철은 아침마다 붐빈다")

    assert same == lighthouse  # deterministic: the cache depends on it
    assert cosine(lighthouse, same) == pytest.approx(1.0)
    assert cosine(lighthouse, related) > cosine(lighthouse, unrelated)
    assert provider.vector("") and len(provider.vector("")) == 256


async def test_stream_cancellation_closes_the_upstream_connection() -> None:
    """Contract: cancelling a stream must close the socket, or the provider keeps generating and billing."""
    disconnected = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        body = await reader.read(4096) if False else b""  # request body already buffered by httpx
        del body
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        try:
            for index in range(200):
                frame = sse({"choices": [{"delta": {"content": f"{index}"}}]})
                writer.write(f"{len(frame):x}\r\n".encode() + frame + b"\r\n")
                await writer.drain()
                await asyncio.sleep(0.02)
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            disconnected.set()
            writer.close()

    server = await asyncio.start_server(serve, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    provider = OpenAICompatibleLLMProvider(
        HttpProviderConfig(base_url=f"http://127.0.0.1:{port}/v1", model="m")
    )
    try:
        stream = provider.stream(REQUEST, timeout_s=5)
        assert (await anext(stream)).delta is not None
        await stream.aclose()  # type: ignore[attr-defined]
        await asyncio.wait_for(disconnected.wait(), timeout=2.0)
    finally:
        await provider.aclose()
        server.close()
        await server.wait_closed()
