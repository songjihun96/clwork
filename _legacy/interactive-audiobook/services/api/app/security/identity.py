"""Verification of Sign in with Apple / Google ID tokens.

The mobile app obtains an ID token from the native SDK and sends it to the API.
The API verifies signature (JWKS), issuer, audience (our client IDs), expiry and nonce.
No provider secret is needed for this flow.
"""

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import jwt
from starlette.concurrency import run_in_threadpool
from story_core.models.user import IdentityProvider

from app.config import Settings
from app.core.errors import ServiceUnavailable, Unauthorized

APPLE_ISSUERS = ("https://appleid.apple.com",)
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


class NonceMode(StrEnum):
    # Apple: the app sends SHA-256(raw nonce) to Apple and the token carries that hash;
    # the API receives the raw nonce.
    SHA256 = "sha256"
    # Google: the token carries the nonce exactly as the app supplied it.
    PLAIN = "plain"


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    provider: IdentityProvider
    subject: str
    email: str | None
    email_verified: bool


class IdentityTokenVerifier(Protocol):
    provider: IdentityProvider

    async def verify(self, id_token: str, *, nonce: str | None) -> VerifiedIdentity: ...


class SigningKeyResolver(Protocol):
    def get_signing_key(self, token: str) -> Any: ...


class JwksKeyResolver:
    """Fetches and caches the provider's public keys. Blocking I/O — call from a thread."""

    def __init__(self, url: str, *, timeout_s: float) -> None:
        self._client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=int(max(timeout_s, 1)))

    def get_signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


def _as_bool(value: Any) -> bool:
    # Apple sends "true"/"false" strings in some versions, booleans in others.
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


class OidcIdTokenVerifier:
    def __init__(
        self,
        *,
        provider: IdentityProvider,
        issuers: tuple[str, ...],
        audiences: list[str],
        key_resolver: SigningKeyResolver,
        nonce_mode: NonceMode,
    ) -> None:
        self.provider = provider
        self._issuers = issuers
        self._audiences = audiences
        self._keys = key_resolver
        self._nonce_mode = nonce_mode

    async def verify(self, id_token: str, *, nonce: str | None) -> VerifiedIdentity:
        if not self._audiences:
            raise ServiceUnavailable(
                f"{self.provider} sign-in is not configured", code="provider_not_configured"
            )
        try:
            key = await run_in_threadpool(self._keys.get_signing_key, id_token)
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self._audiences,
                leeway=30,
                options={"require": ["iss", "aud", "sub", "iat", "exp"]},
            )
        except (jwt.PyJWKClientError, jwt.InvalidTokenError) as exc:
            raise Unauthorized("Invalid identity token", code="invalid_identity_token") from exc

        if claims.get("iss") not in self._issuers:
            raise Unauthorized("Invalid identity token", code="invalid_identity_token")
        self._check_nonce(claims.get("nonce"), nonce)

        email = claims.get("email")
        return VerifiedIdentity(
            provider=self.provider,
            subject=str(claims["sub"]),
            email=str(email).lower() if email else None,
            email_verified=_as_bool(claims.get("email_verified", False)),
        )

    def _check_nonce(self, claim: Any, raw_nonce: str | None) -> None:
        if raw_nonce is None and claim is None:
            return
        if raw_nonce is None or claim is None:
            raise Unauthorized("Nonce mismatch", code="invalid_identity_token")
        expected = (
            hashlib.sha256(raw_nonce.encode()).hexdigest()
            if self._nonce_mode is NonceMode.SHA256
            else raw_nonce
        )
        if not hmac.compare_digest(str(claim), expected):
            raise Unauthorized("Nonce mismatch", code="invalid_identity_token")


def build_identity_verifiers(settings: Settings) -> dict[IdentityProvider, IdentityTokenVerifier]:
    return {
        IdentityProvider.APPLE: OidcIdTokenVerifier(
            provider=IdentityProvider.APPLE,
            issuers=APPLE_ISSUERS,
            audiences=settings.apple_client_ids,
            key_resolver=JwksKeyResolver(APPLE_JWKS_URL, timeout_s=settings.identity_jwks_timeout_s),
            nonce_mode=NonceMode.SHA256,
        ),
        IdentityProvider.GOOGLE: OidcIdTokenVerifier(
            provider=IdentityProvider.GOOGLE,
            issuers=GOOGLE_ISSUERS,
            audiences=settings.google_client_ids,
            key_resolver=JwksKeyResolver(GOOGLE_JWKS_URL, timeout_s=settings.identity_jwks_timeout_s),
            nonce_mode=NonceMode.PLAIN,
        ),
    }
