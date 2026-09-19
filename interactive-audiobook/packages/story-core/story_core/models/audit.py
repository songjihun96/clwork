import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from story_core.db.types import JSONDocument
from story_core.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Security-relevant events.

    ``actor_user_id`` intentionally has no foreign key: audit entries must outlive
    account deletion (pseudonymised later by the retention job).
    ``details`` must never contain passwords, tokens, emails, or content text.
    """

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict, nullable=False)
