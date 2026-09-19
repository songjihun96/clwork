"""S3-compatible object storage (AWS S3, Cloudflare R2, other S3 APIs).

boto3 is synchronous; calls run in worker threads with explicit connect/read timeouts and bounded
retries. Presigned GET URLs are computed locally (no network call).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from story_core.storage.base import ObjectNotFound, StorageError, validate_key


@dataclass(frozen=True, slots=True)
class S3Options:
    bucket: str
    region: str = "auto"  # "auto" is what Cloudflare R2 expects
    endpoint_url: str | None = None  # None → AWS; R2: https://<account>.r2.cloudflarestorage.com
    access_key_id: str | None = None
    secret_access_key: str | None = None
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 30.0
    max_attempts: int = 3


class S3CompatibleStorage:
    def __init__(self, options: S3Options, *, client: Any | None = None) -> None:
        self._bucket = options.bucket
        self._client = client or boto3.client(
            "s3",
            region_name=options.region,
            endpoint_url=options.endpoint_url,
            aws_access_key_id=options.access_key_id,
            aws_secret_access_key=options.secret_access_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=options.connect_timeout_s,
                read_timeout=options.read_timeout_s,
                retries={"max_attempts": options.max_attempts, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        validate_key(key)
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get_bytes(self, key: str) -> bytes:
        validate_key(key)

        def _get() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    raise ObjectNotFound(key) from exc
                raise StorageError("object read failed") from exc
            body: bytes = response["Body"].read()
            return body

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        validate_key(key)

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                    return False
                raise StorageError("object head failed") from exc
            return True

        return await asyncio.to_thread(_head)

    async def signed_get_url(self, key: str, *, expires_in_s: int) -> tuple[str, int]:
        validate_key(key)
        url: str = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=expires_in_s
        )
        return url, int(time.time()) + expires_in_s
