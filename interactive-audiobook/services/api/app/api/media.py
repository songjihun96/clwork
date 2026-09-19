"""Serves locally stored media behind HMAC-signed, expiring URLs (development / single-host setups).

With S3/R2 storage, clients receive presigned bucket URLs instead and this route is not used.
No bearer token: audio players cannot attach headers, so the signature is the credential.
Range requests are supported (seeking) by Starlette's FileResponse.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from story_core.storage.base import StorageError
from story_core.storage.local import LocalFileStorage

from app.core.errors import AppError, NotFound
from app.dependencies import StorageDep

router = APIRouter(prefix="/media", tags=["media"])

_CONTENT_TYPES = {
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class InvalidSignature(AppError):
    status_code = 403
    code = "invalid_media_signature"
    message = "Media link is invalid or expired"


@router.get("/{key:path}", include_in_schema=False)
async def get_media(
    key: str,
    storage: StorageDep,
    exp: Annotated[int, Query(ge=0)],
    sig: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
) -> FileResponse:
    if not isinstance(storage, LocalFileStorage):
        raise NotFound()
    try:
        valid = storage.verify_signature(key, exp, sig)
        path = storage.path_for(key)
    except StorageError as exc:
        raise NotFound() from exc
    if not valid:
        raise InvalidSignature()
    extension = key.rsplit(".", 1)[-1].lower()
    content_type = _CONTENT_TYPES.get(extension)
    if content_type is None or not path.is_file():
        raise NotFound()
    max_age = max(0, exp - int(time.time()))
    return FileResponse(
        path, media_type=content_type, headers={"Cache-Control": f"private, max-age={max_age}"}
    )
