import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from story_core.models.user import IdentityProvider

from app.core.errors import NotFound
from app.dependencies import (
    SettingsDep,
    get_auth_service,
    get_identity_verifiers,
    get_rate_limiter,
    ip_rate_limit,
)
from app.schemas.auth import (
    IdentityLoginRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.security.identity import IdentityTokenVerifier
from app.security.ratelimit import RateLimiter, enforce
from app.services.auth_service import AuthService, IssuedTokens, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _token_response(issued: IssuedTokens) -> TokenResponse:
    user = issued.user
    return TokenResponse(
        access_token=issued.access_token,
        access_token_expires_at=issued.access_token_expires_at,
        refresh_token=issued.refresh_token,
        refresh_token_expires_at=issued.refresh_token_expires_at,
        user=UserResponse(
            id=user.id, email=user.email, display_name=user.display_name, created_at=user.created_at
        ),
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=TokenResponse,
    responses={**ERROR_RESPONSES, 409: {"model": ErrorResponse}},
    dependencies=[ip_rate_limit("register", "rate_limit_register_per_ip")],
)
async def register(body: RegisterRequest, request: Request, service: AuthServiceDep) -> TokenResponse:
    issued = await service.register_email(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        user_agent=_user_agent(request),
    )
    return _token_response(issued)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=ERROR_RESPONSES,
    dependencies=[ip_rate_limit("login", "rate_limit_login_per_ip")],
)
async def login(
    body: LoginRequest,
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> TokenResponse:
    if settings.rate_limit_enabled:
        # Per-account limit slows distributed guessing against one account.
        # The key is hashed so no email address is stored in Redis.
        account_key = hashlib.sha256(normalize_email(body.email).encode()).hexdigest()
        await enforce(
            limiter,
            f"login:acct:{account_key}",
            limit=settings.rate_limit_login_per_account,
            window_s=settings.rate_limit_window_seconds,
        )
    issued = await service.login_email(
        email=body.email, password=body.password, user_agent=_user_agent(request)
    )
    return _token_response(issued)


@router.post(
    "/oauth/{provider}",
    response_model=TokenResponse,
    responses={**ERROR_RESPONSES, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[ip_rate_limit("login", "rate_limit_login_per_ip")],
)
async def identity_login(
    provider: IdentityProvider,
    body: IdentityLoginRequest,
    request: Request,
    service: AuthServiceDep,
    verifiers: Annotated[dict[IdentityProvider, IdentityTokenVerifier], Depends(get_identity_verifiers)],
) -> TokenResponse:
    verifier = verifiers.get(provider)
    if verifier is None:
        raise NotFound("Unknown identity provider")
    identity = await verifier.verify(body.id_token, nonce=body.nonce)
    issued = await service.login_identity(
        identity, display_name=body.display_name, user_agent=_user_agent(request)
    )
    return _token_response(issued)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=ERROR_RESPONSES,
    dependencies=[ip_rate_limit("refresh", "rate_limit_refresh_per_ip")],
)
async def refresh(body: RefreshRequest, request: Request, service: AuthServiceDep) -> TokenResponse:
    issued = await service.refresh(refresh_token=body.refresh_token, user_agent=_user_agent(request))
    return _token_response(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES)
async def logout(body: LogoutRequest, service: AuthServiceDep) -> None:
    await service.logout(refresh_token=body.refresh_token)
