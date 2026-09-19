"""HMAC-signed, expiring media URLs for storage backends without native presigning (local files).

The signature covers the object key and the expiry, so a URL cannot be reused for another object or
extended. Players cannot attach Authorization headers, which is why media uses signed URLs.
"""

import hashlib
import hmac
import time
from collections.abc import Callable
from urllib.parse import quote, urlencode


class MediaUrlSigner:
    def __init__(
        self,
        *,
        secret: bytes,
        base_url: str,
        path_prefix: str = "/v1/media",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("media signing secret must be at least 32 bytes")
        self._secret = secret
        self._base_url = base_url.rstrip("/")
        self._prefix = path_prefix
        self._clock = clock

    def _signature(self, key: str, expires_at: int) -> str:
        message = f"{key}\n{expires_at}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def sign(self, key: str, *, expires_in_s: int) -> tuple[str, int]:
        expires_at = int(self._clock()) + expires_in_s
        query = urlencode({"exp": expires_at, "sig": self._signature(key, expires_at)})
        return f"{self._base_url}{self._prefix}/{quote(key)}?{query}", expires_at

    def verify(self, key: str, expires_at: int, signature: str) -> bool:
        if expires_at < int(self._clock()):
            return False
        return hmac.compare_digest(self._signature(key, expires_at), signature)
