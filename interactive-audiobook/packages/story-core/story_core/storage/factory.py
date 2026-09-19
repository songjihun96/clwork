"""Builds the configured StorageProvider. Shared by the API and the worker so both see the same objects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from story_core.storage.base import StorageProvider
from story_core.storage.local import LocalFileStorage
from story_core.storage.s3 import S3CompatibleStorage, S3Options
from story_core.storage.signing import MediaUrlSigner


@dataclass(frozen=True, slots=True)
class StorageConfig:
    backend: Literal["local", "s3"]
    local_root: Path
    public_base_url: str
    media_signing_secret: bytes
    s3: S3Options | None = None


def build_storage(config: StorageConfig) -> StorageProvider:
    if config.backend == "s3":
        if config.s3 is None:
            raise ValueError("S3 storage selected but S3 options are missing")
        return S3CompatibleStorage(config.s3)
    signer = MediaUrlSigner(secret=config.media_signing_secret, base_url=config.public_base_url)
    return LocalFileStorage(config.local_root, signer=signer)
