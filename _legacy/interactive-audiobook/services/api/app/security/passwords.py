"""Password hashing with argon2id.

Hashing is CPU/memory heavy, so async callers go through the thread pool.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.concurrency import run_in_threadpool

_hasher = PasswordHasher()
# Verified when the account does not exist, so response time does not reveal whether an email is registered.
_DUMMY_HASH = _hasher.hash("timing-equalisation-dummy-password")


def hash_password_sync(password: str) -> str:
    return _hasher.hash(password)


def verify_password_sync(password_hash: str | None, password: str) -> bool:
    target = password_hash or _DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


async def hash_password(password: str) -> str:
    return await run_in_threadpool(hash_password_sync, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    return await run_in_threadpool(verify_password_sync, password_hash, password)
