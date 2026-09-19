"""Authentication use cases. Owns the transaction boundary (commit) for each operation."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from story_core.models.user import AuthIdentity, RefreshToken, User, UserStatus
from story_core.time import utcnow

from app.core.errors import Conflict, Unauthorized
from app.repositories.audit import AuditAction, AuditRepository
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.security import passwords
from app.security.identity import VerifiedIdentity
from app.security.tokens import AccessTokenClaims, TokenService, generate_refresh_token, hash_refresh_token

_INVALID_CREDENTIALS = "Invalid email or password"


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    user: User
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        tokens: TokenService,
        *,
        refresh_ttl: timedelta,
        recent_auth_window: timedelta,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._refresh_ttl = refresh_ttl
        self._recent_auth_window = recent_auth_window
        self._clock = clock
        self._users = UserRepository(session)
        self._refresh = RefreshTokenRepository(session)
        self._audit = AuditRepository(session)

    # ----- email / password -----

    async def register_email(
        self, *, email: str, password: str, display_name: str | None, user_agent: str | None
    ) -> IssuedTokens:
        email = normalize_email(email)
        if await self._users.get_by_email(email) is not None:
            raise Conflict("An account with this email already exists", code="email_taken")

        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=await passwords.hash_password(password),
            display_name=display_name,
        )
        try:
            await self._users.add(user)
        except IntegrityError as exc:  # concurrent registration with the same email
            await self._session.rollback()
            raise Conflict("An account with this email already exists", code="email_taken") from exc
        issued, _ = self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        self._audit.record(AuditAction.USER_REGISTERED, actor_user_id=user.id, details={"method": "email"})
        await self._session.commit()
        return issued

    async def login_email(self, *, email: str, password: str, user_agent: str | None) -> IssuedTokens:
        user = await self._users.get_by_email(normalize_email(email))
        # Always run a hash verification so timing does not reveal whether the account exists.
        valid = await passwords.verify_password(user.password_hash if user else None, password)

        if user is None or not valid or user.status != UserStatus.ACTIVE:
            self._audit.record(
                AuditAction.LOGIN_FAILED,
                actor_user_id=user.id if user else None,
                details={"method": "email", "reason": "inactive" if user and valid else "credentials"},
            )
            await self._session.commit()
            raise Unauthorized(_INVALID_CREDENTIALS, code="invalid_credentials")

        if user.password_hash and passwords.needs_rehash(user.password_hash):
            user.password_hash = await passwords.hash_password(password)
        issued, _ = self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        self._audit.record(AuditAction.LOGIN_SUCCEEDED, actor_user_id=user.id, details={"method": "email"})
        await self._session.commit()
        return issued

    # ----- Apple / Google -----

    async def login_identity(
        self, identity: VerifiedIdentity, *, display_name: str | None, user_agent: str | None
    ) -> IssuedTokens:
        user = await self._users.get_by_identity(identity.provider, identity.subject)
        created = False
        if user is None:
            email = identity.email if identity.email_verified else None
            if email and await self._users.get_by_email(email) is not None:
                # Never auto-link: provider email verification strength varies (account takeover risk).
                raise Conflict(
                    "An account with this email already exists. Sign in with it first to link.",
                    code="account_link_required",
                )
            user = User(
                id=uuid.uuid4(),
                email=email,
                display_name=display_name,
                email_verified_at=self._clock() if email else None,
            )
            try:
                await self._users.add(user)
                await self._users.add_identity(
                    AuthIdentity(
                        user_id=user.id,
                        provider=identity.provider,
                        subject=identity.subject,
                        email_at_link=email,
                    )
                )
            except IntegrityError as exc:  # concurrent first sign-in with the same identity or email
                await self._session.rollback()
                raise Conflict("Sign-in already in progress, retry", code="identity_conflict") from exc
            created = True
        elif user.status != UserStatus.ACTIVE:
            raise Unauthorized("Account is not active", code="account_inactive")

        issued, _ = self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        self._audit.record(
            AuditAction.USER_REGISTERED if created else AuditAction.IDENTITY_LOGIN_SUCCEEDED,
            actor_user_id=user.id,
            details={"method": str(identity.provider)},
        )
        await self._session.commit()
        return issued

    # ----- refresh / logout -----

    async def refresh(self, *, refresh_token: str, user_agent: str | None) -> IssuedTokens:
        now = self._clock()
        stored = await self._refresh.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if stored is None:
            raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")

        if stored.revoked_at is not None:
            # A rotated token was presented again: treat the whole family as compromised.
            await self._refresh.revoke_family(stored.family_id, at=now)
            self._audit.record(
                AuditAction.REFRESH_REUSE_DETECTED,
                actor_user_id=stored.user_id,
                target_type="refresh_token_family",
                target_id=str(stored.family_id),
            )
            await self._session.commit()
            raise Unauthorized("Refresh token was already used", code="refresh_token_reused")

        if stored.expires_at <= now:
            raise Unauthorized("Refresh token expired", code="refresh_token_expired")

        user = await self._users.get(stored.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise Unauthorized("Account is not active", code="account_inactive")

        issued, new_record = self._issue(user, family_id=stored.family_id, user_agent=user_agent)
        stored.revoked_at = now
        stored.replaced_by_id = new_record.id
        await self._session.commit()
        return issued

    async def logout(self, *, refresh_token: str) -> None:
        stored = await self._refresh.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if stored is None:
            return  # idempotent
        await self._refresh.revoke_family(stored.family_id, at=self._clock())
        self._audit.record(AuditAction.LOGOUT, actor_user_id=stored.user_id)
        await self._session.commit()

    # ----- account deletion -----

    async def delete_account(self, *, user: User, claims: AccessTokenClaims, password: str | None) -> None:
        if user.password_hash is not None:
            if password is None or not await passwords.verify_password(user.password_hash, password):
                raise Unauthorized("Password confirmation failed", code="reauthentication_required")
        elif self._clock() - claims.issued_at > self._recent_auth_window:
            raise Unauthorized(
                "Please sign in again before deleting your account", code="reauthentication_required"
            )

        # External resources (voice profiles, stored audio) will be deleted by queued jobs
        # once those features exist (docs/security.md §6).
        self._audit.record(
            AuditAction.USER_DELETED, actor_user_id=user.id, target_type="user", target_id=str(user.id)
        )
        await self._users.delete(user.id)
        await self._session.commit()

    # ----- helpers -----

    def _issue(
        self, user: User, *, family_id: uuid.UUID, user_agent: str | None
    ) -> tuple[IssuedTokens, RefreshToken]:
        now = self._clock()
        access_token, access_expires_at = self._tokens.issue_access_token(user.id)
        raw_refresh = generate_refresh_token()
        record = RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=now + self._refresh_ttl,
            user_agent=(user_agent or "")[:200] or None,
        )
        self._refresh.add(record)
        issued = IssuedTokens(
            user=user,
            access_token=access_token,
            access_token_expires_at=access_expires_at,
            refresh_token=raw_refresh,
            refresh_token_expires_at=record.expires_at,
        )
        return issued, record
