"""Request context middleware: request id, access log, security headers.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware) so it does not buffer
streaming responses.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from story_core.logging import request_id_ctx

logger = logging.getLogger("app.request")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def route_template(scope: Scope) -> str:
    """Matched route as a template (``/v1/auth/oauth/{provider}``), never raw user-supplied values.

    Rebuilt from the request path because nested router prefixes are not part of ``route.path``.
    Unmatched requests are reported as "unmatched" so arbitrary probe paths never reach the logs.
    """
    if scope.get("route") is None:
        return "unmatched"
    path: str = scope.get("path", "")
    params: dict[str, object] = scope.get("path_params") or {}
    if not params:
        return path
    for name, value in params.items():
        text = str(value)
        if "/" in text:
            path = path.replace(text, f"{{{name}}}", 1)
    names_by_value = {str(value): name for name, value in params.items() if "/" not in str(value)}
    return "/".join(
        f"{{{names_by_value[segment]}}}" if segment in names_by_value else segment
        for segment in path.split("/")
    )


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "route": route_template(scope),
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_ctx.reset(token)
