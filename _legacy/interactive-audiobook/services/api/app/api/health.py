import asyncio
import logging
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

_CHECK_TIMEOUT_S = 2.0


@router.get("/live")
async def live() -> dict[str, str]:
    """Process is up. Does not touch dependencies (used for container restarts)."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Dependencies reachable (used to route traffic). Failure details go to logs, not the response."""
    engine = cast(AsyncEngine, request.app.state.engine)
    redis = cast(Redis, request.app.state.redis)
    checks: dict[str, str] = {}

    async def check_db() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def check_redis() -> None:
        await redis.ping()

    for name, check in (("database", check_db), ("redis", check_redis)):
        try:
            await asyncio.wait_for(check(), timeout=_CHECK_TIMEOUT_S)
            checks[name] = "ok"
        except Exception as exc:
            logger.warning("readiness_check_failed", extra={"check": name, "exc_type": type(exc).__name__})
            checks[name] = "fail"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "fail", "checks": checks}, status_code=200 if healthy else 503
    )
