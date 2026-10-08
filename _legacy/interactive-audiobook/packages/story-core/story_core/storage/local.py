"""Filesystem storage for development, tests and single-host setups.

Writes are atomic (temp file + rename) so a reader never sees a partially written object. Signed URLs
point at the API's media route, which verifies the HMAC before streaming the file.
"""

import asyncio
import os
import tempfile
from pathlib import Path

from story_core.storage.base import ObjectNotFound, StorageError, validate_key
from story_core.storage.signing import MediaUrlSigner


class LocalFileStorage:
    def __init__(self, root: Path, *, signer: MediaUrlSigner | None = None) -> None:
        self._root = root.resolve()
        self._signer = signer

    def path_for(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        if self._root not in path.parents:
            raise StorageError("storage key escapes the storage root")
        return path

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self.path_for(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_write)

    async def get_bytes(self, key: str) -> bytes:
        path = self.path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.path_for(key).is_file)

    async def signed_get_url(self, key: str, *, expires_in_s: int) -> tuple[str, int]:
        if self._signer is None:
            raise StorageError("local storage has no URL signer configured")
        validate_key(key)
        return self._signer.sign(key, expires_in_s=expires_in_s)

    def verify_signature(self, key: str, expires_at: int, signature: str) -> bool:
        return self._signer is not None and self._signer.verify(key, expires_at, signature)
