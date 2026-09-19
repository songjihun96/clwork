"""Shared HTTP plumbing for OpenAI-compatible providers (hosted endpoints and self-hosted vLLM).

Keeping the error mapping in one place is what makes the retry policy uniform: a wrapper decides what to
do from the exception type alone and never inspects vendor payloads.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from story_core.providers.base import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderContentRejected,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

# Payloads carry book text and prompts, so only the shape of a failure is logged, never the body.
_MAX_ERROR_DETAIL = 200


@dataclass(frozen=True, slots=True)
class HttpProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None
    # Vendor-specific headers (e.g. api-version). Never logged.
    headers: tuple[tuple[str, str], ...] = ()

    def endpoint(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


def build_client(config: HttpProviderConfig, *, timeout_s: float = 30.0) -> httpx.AsyncClient:
    headers = {"Accept": "application/json", **dict(config.headers)}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(timeout_s, connect=5.0))


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return None  # HTTP-date form: fall back to the wrapper's backoff


def error_detail(body: bytes | str) -> str:
    """The provider's own error code, if it sent one — never the request content."""
    text = body.decode(errors="replace") if isinstance(body, bytes) else body
    try:
        payload = json.loads(text)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = error.get("code") or error.get("type") or error.get("message") or ""
            return str(detail)[:_MAX_ERROR_DETAIL]
        if isinstance(error, str):
            return error[:_MAX_ERROR_DETAIL]
    except (json.JSONDecodeError, AttributeError):
        pass
    return text.strip()[:_MAX_ERROR_DETAIL]


def raise_for_status(response: httpx.Response, body: bytes | str) -> None:
    status = response.status_code
    if status < 400:
        return
    detail = error_detail(body)
    if status in (401, 403):
        raise ProviderAuthError(f"provider rejected credentials ({status})")
    if status == 429:
        raise ProviderRateLimited(f"rate limited: {detail}", retry_after_s=_retry_after(response))
    if status == 408 or status == 504:
        raise ProviderTimeout(f"upstream timeout ({status})")
    if status >= 500:
        raise ProviderUnavailable(f"provider unavailable ({status}): {detail}")
    if status == 422 and "content" in detail.lower():
        raise ProviderContentRejected(f"content rejected: {detail}")
    raise ProviderBadRequest(f"provider rejected the request ({status}): {detail}")


def wrap_transport_error(exc: Exception) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeout(f"{type(exc).__name__}")
    if isinstance(exc, httpx.HTTPError):
        return ProviderUnavailable(f"{type(exc).__name__}")
    return ProviderUnavailable(f"{type(exc).__name__}")


def decode_json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderUnavailable(f"provider returned invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailable("provider returned an unexpected JSON shape")
    return payload
