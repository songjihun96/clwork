"""S3-compatible storage contract test.

Runs only when TEST_S3_ENDPOINT is set, e.g. against Adobe S3Mock:
    docker run -d -p 9090:9090 -e COM_ADOBE_TESTING_S3MOCK_STORE_INITIAL_BUCKETS=audiobook-test adobe/s3mock:5.2.2
    TEST_S3_ENDPOINT=http://127.0.0.1:9090 pytest tests/test_storage_s3.py
S3Mock does not validate signatures, so presigned-URL *authentication* must still be checked against
real R2/S3 before production; this test covers the API calls and URL shape.
"""

import asyncio
import os
import urllib.request
import uuid

import pytest

from story_core.storage.base import ObjectNotFound, StorageError
from story_core.storage.s3 import S3CompatibleStorage, S3Options

ENDPOINT = os.environ.get("TEST_S3_ENDPOINT")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="TEST_S3_ENDPOINT not set")


@pytest.fixture
def s3() -> S3CompatibleStorage:
    return S3CompatibleStorage(
        S3Options(
            bucket=os.environ.get("TEST_S3_BUCKET", "audiobook-test"),
            region="us-east-1",
            endpoint_url=ENDPOINT,
            access_key_id="test",
            secret_access_key="test",  # noqa: S106
        )
    )


async def test_put_get_exists_delete(s3: S3CompatibleStorage) -> None:
    key = f"audio/paragraphs/{uuid.uuid4().hex}.wav"
    assert not await s3.exists(key)
    await s3.put_bytes(key, b"RIFF-test", content_type="audio/wav")
    assert await s3.exists(key)
    assert await s3.get_bytes(key) == b"RIFF-test"
    await s3.delete(key)
    assert not await s3.exists(key)
    with pytest.raises(ObjectNotFound):
        await s3.get_bytes(key)
    with pytest.raises(StorageError):
        await s3.put_bytes("../escape", b"x", content_type="text/plain")


async def test_presigned_get_url_downloads_the_object(s3: S3CompatibleStorage) -> None:
    key = f"audio/paragraphs/{uuid.uuid4().hex}.wav"
    await s3.put_bytes(key, b"presigned-body", content_type="audio/wav")
    url, expires_at = await s3.signed_get_url(key, expires_in_s=120)
    assert "X-Amz-Signature=" in url and "X-Amz-Expires=120" in url and expires_at > 0

    def download() -> bytes:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - test endpoint
            body: bytes = response.read()
            return body

    assert await asyncio.to_thread(download) == b"presigned-body"
    await s3.delete(key)
