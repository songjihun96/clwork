"""Structured JSON logging with redaction of sensitive fields.

Rules (docs/security.md §7):
- Never log request/response bodies.
- Anything passed via ``extra=`` whose key looks sensitive is masked, recursively.
"""

import json
import logging
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "email",
    "audio",
    "transcript",
    "prompt",
    "text",
    "nonce",
)
_MAX_DEPTH = 6

# Attributes present on every LogRecord; anything else came from `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact(value: Any, _depth: int = 0) -> Any:
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(k): REDACTED if _is_sensitive(str(k)) else redact(v, _depth + 1) for k, v in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _json_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    return handler


def configure_logging(level: str) -> None:
    """Own the root logger. For processes we start ourselves (API, worker)."""
    root = logging.getLogger()
    root.handlers[:] = [_json_handler()]
    root.setLevel(level.upper())
    # Uvicorn's access log would duplicate our request log and includes query strings.
    logging.getLogger("uvicorn.access").disabled = True


def configure_logger(name: str, level: str) -> None:
    """Own one logger tree, leaving the root alone.

    Some frameworks configure the root logger themselves after we start (the LiveKit agents CLI does).
    Replacing the root handler there gets every line emitted twice — once by each handler — so instead our
    own loggers stop propagating and keep the redacting formatter, and the framework keeps its own.
    """
    logger = logging.getLogger(name)
    logger.handlers[:] = [_json_handler()]
    logger.setLevel(level.upper())
    logger.propagate = False
