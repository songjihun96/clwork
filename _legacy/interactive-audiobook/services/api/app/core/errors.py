"""Application errors and a single JSON error envelope.

Every error response has the shape ``{"error": {"code", "message", "request_id"}}``.
Internal exception details never reach the client.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from story_core.reading.sessions import (
    BookUnavailable,
    InvalidPosition,
    PlaybackActionRejected,
    PositionConflict,
    ReadingError,
    SessionNotFound,
)

logger = logging.getLogger(__name__)

# Domain errors from story_core mapped to HTTP. Other users' sessions and unlicensed books are 404, not 403.
_READING_ERRORS: dict[type[ReadingError], tuple[int, str]] = {
    SessionNotFound: (404, "Reading session not found"),
    BookUnavailable: (404, "Book not found"),
    InvalidPosition: (422, "Position does not exist in this book"),
    PositionConflict: (409, "The position was updated from another device"),
    PlaybackActionRejected: (409, "This playback action is not possible in the current state"),
}


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.headers = headers
        super().__init__(self.message)


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "Not allowed"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests"

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(headers={"Retry-After": str(max(retry_after_s, 1))})


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Service unavailable"


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else None


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": _request_id(request)}
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(ReadingError)
    async def _reading_error(request: Request, exc: ReadingError) -> JSONResponse:
        status, message = _READING_ERRORS.get(type(exc), (400, "Invalid reading session request"))
        return error_response(request, status, exc.code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Strip "input"/"ctx": they echo user-submitted values such as passwords.
        details = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
            for err in exc.errors()
        ]
        return error_response(request, 422, "validation_error", "Invalid request", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return error_response(
            request, exc.status_code, code, message, headers=dict(exc.headers) if exc.headers else None
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"exc_type": type(exc).__name__})
        return error_response(request, 500, "internal_error", "Internal server error")
