import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from story_core.models.audit import AuditLog


class AuditAction(StrEnum):
    USER_REGISTERED = "user.registered"
    USER_DELETED = "user.deleted"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    IDENTITY_LOGIN_SUCCEEDED = "auth.identity_login_succeeded"
    REFRESH_REUSE_DETECTED = "auth.refresh_reuse_detected"
    LOGOUT = "auth.logout"
    BOOK_UPLOADED = "book.uploaded"
    BOOK_RIGHTS_UPDATED = "book.rights_updated"
    BOOK_PROCESSING_REQUESTED = "book.processing_requested"
    USER_ROLE_CHANGED = "user.role_changed"


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        action: AuditAction,
        *,
        actor_user_id: uuid.UUID | None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details or {},
            )
        )
