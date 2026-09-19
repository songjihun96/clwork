"""Access tokens (short-lived JWT) and refresh tokens (opaque, stored hashed).

Isolated here so the token scheme can later move to an external IdP or to
``kid``-based key rotation without touching the rest of the code.
"""

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import SecretStr
from story_core.time import utcnow

from app.core.errors import Unauthorized

_ALGORITHM = "HS256"
_ACCESS_TYPE = "access"
_LEEWAY = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    token_id: str
    issued_at: datetime
    expires_at: datetime


class TokenService:
    def __init__(
        self,
        *,
        secret: SecretStr,
        issuer: str,
        audience: str,
        access_ttl: timedelta,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl
        self._clock = clock

    def issue_access_token(self, user_id: uuid.UUID) -> tuple[str, datetime]:
        now = self._clock()
        expires_at = now + self._access_ttl
        claims = {
            "sub": str(user_id),
            "typ": _ACCESS_TYPE,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._secret.get_secret_value(), algorithm=_ALGORITHM)
        return token, expires_at

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            claims = jwt.decode(
                token,
                self._secret.get_secret_value(),
                algorithms=[_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=_LEEWAY,
                options={"require": ["sub", "typ", "iss", "aud", "iat", "exp", "jti"]},
            )
            if claims.get("typ") != _ACCESS_TYPE:
                raise jwt.InvalidTokenError("wrong token type")
            user_id = uuid.UUID(str(claims["sub"]))
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise Unauthorized("Invalid or expired access token", code="invalid_token") from exc
        return AccessTokenClaims(
            user_id=user_id,
            token_id=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )


def generate_refresh_token() -> str:
    """256 bits of randomness, URL-safe, 43 chars — small enough for iOS Keychain limits."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
