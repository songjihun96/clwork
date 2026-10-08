"""FastAPI dependency providers.

Long-lived resources are created once in ``create_app`` and stored on ``app.state``;
these functions only hand them out, so tests can inject fakes through ``create_app``.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from story_core.jobs.queue import JobQueue
from story_core.models.user import IdentityProvider, User, UserRole, UserStatus
from story_core.storage.base import StorageProvider

from app.config import Settings
from app.core.errors import Forbidden, Unauthorized
from app.repositories.users import UserRepository
from app.security.identity import IdentityTokenVerifier
from app.security.ratelimit import RateLimiter, client_ip, enforce
from app.security.tokens import AccessTokenClaims, TokenService
from app.security.uploads import UploadScanner
from app.services.auth_service import AuthService

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_token_service(request: Request) -> TokenService:
    return cast(TokenService, request.app.state.token_service)


def get_rate_limiter(request: Request) -> RateLimiter:
    return cast(RateLimiter, request.app.state.rate_limiter)


def get_identity_verifiers(request: Request) -> Mapping[IdentityProvider, IdentityTokenVerifier]:
    return cast(Mapping[IdentityProvider, IdentityTokenVerifier], request.app.state.identity_verifiers)


def get_storage(request: Request) -> StorageProvider:
    return cast(StorageProvider, request.app.state.storage)


def get_job_queue(request: Request) -> JobQueue:
    return cast(JobQueue, request.app.state.job_queue)


def get_upload_scanner(request: Request) -> UploadScanner:
    return cast(UploadScanner, request.app.state.upload_scanner)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with sessionmaker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_auth_service(
    session: DbSession, settings: SettingsDep, tokens: Annotated[TokenService, Depends(get_token_service)]
) -> AuthService:
    return AuthService(
        session,
        tokens,
        refresh_ttl=timedelta(seconds=settings.refresh_token_ttl_seconds),
        recent_auth_window=timedelta(seconds=settings.recent_auth_window_seconds),
    )


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user: User
    claims: AccessTokenClaims


async def get_current_user(
    session: DbSession,
    tokens: Annotated[TokenService, Depends(get_token_service)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized(headers={"WWW-Authenticate": "Bearer"})
    claims = tokens.decode_access_token(credentials.credentials)
    user = await UserRepository(session).get(claims.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise Unauthorized("Invalid or expired access token", code="invalid_token")
    return CurrentUser(user=user, claims=claims)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def require_admin(current: CurrentUserDep) -> CurrentUser:
    if current.user.role != UserRole.ADMIN:
        raise Forbidden("Administrator role required", code="admin_required")
    return current


AdminDep = Annotated[CurrentUser, Depends(require_admin)]
StorageDep = Annotated[StorageProvider, Depends(get_storage)]
JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]


def user_rate_limit(scope: str, limit_setting: str, *, window_s: int = 60) -> Any:
    """Per-account limit for endpoints that cost money per call (AI providers).

    Keyed by user, not by IP: the cost follows the account, and one household behind a single address
    must not lock each other out.
    """

    async def _dependency(
        settings: SettingsDep,
        current: CurrentUserDep,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        await enforce(
            limiter,
            f"{scope}:user:{current.user.id}",
            limit=int(getattr(settings, limit_setting)),
            window_s=window_s,
        )

    return Depends(_dependency)


def ip_rate_limit(scope: str, limit_setting: str) -> Any:
    """Dependency factory: per-client-IP fixed-window limit for one endpoint group."""

    async def _dependency(
        request: Request,
        settings: SettingsDep,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        ip = client_ip(request, settings.trusted_proxy_count)
        await enforce(
            limiter,
            f"{scope}:ip:{ip}",
            limit=int(getattr(settings, limit_setting)),
            window_s=settings.rate_limit_window_seconds,
        )

    return Depends(_dependency)
