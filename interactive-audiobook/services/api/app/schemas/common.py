from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictRequest(BaseModel):
    """Base for request bodies: unknown fields are rejected, not silently ignored."""

    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Unauthorized"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
}
