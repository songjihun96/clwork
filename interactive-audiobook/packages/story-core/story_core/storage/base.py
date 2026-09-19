"""StorageProvider abstraction (docs/provider-abstraction.md).

Keys are opaque, service-generated paths such as ``books/<uuid>/source/<sha256>.epub``; user-supplied
names never become keys. All buckets are private; clients only ever receive short-lived signed URLs.
"""

import re
from typing import Protocol

_VALID_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,250}$")


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


def validate_key(key: str) -> str:
    if not _VALID_KEY.match(key) or ".." in key.split("/") or "//" in key or key.endswith("/"):
        raise StorageError("invalid storage key")
    return key


class StorageProvider(Protocol):
    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def signed_get_url(self, key: str, *, expires_in_s: int) -> tuple[str, int]:
        """Returns (url, expires_at_epoch_seconds)."""
        ...
