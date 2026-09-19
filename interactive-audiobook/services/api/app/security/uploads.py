"""Upload validation helpers (docs/security.md §4)."""

from typing import Protocol

from fastapi import UploadFile

from app.core.errors import AppError


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"
    message = "File is too large"


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "unsupported_file_type"
    message = "Unsupported file type"


class UploadScanner(Protocol):
    """Malware scanning hook. Production wires a real scanner (e.g. ClamAV sidecar) in Phase 12."""

    async def scan(self, data: bytes, *, declared_name: str | None) -> None:
        """Raise UnsupportedMediaType (or another AppError) to reject the file."""


class NoopUploadScanner:
    async def scan(self, data: bytes, *, declared_name: str | None) -> None:
        return None


async def read_limited(upload: UploadFile, max_bytes: int, *, chunk_size: int = 1024 * 1024) -> bytes:
    """Reads an upload while enforcing the size limit, without trusting Content-Length."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(chunk_size):
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLarge
        chunks.append(chunk)
    return b"".join(chunks)
