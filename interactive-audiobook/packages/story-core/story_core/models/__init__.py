"""Import every model here so Alembic and metadata.create_all see all tables."""

from story_core.models.audio import AudioAsset, AudioKind
from story_core.models.audit import AuditLog
from story_core.models.base import Base
from story_core.models.book import (
    Book,
    BookRights,
    BookStatus,
    Chapter,
    Paragraph,
    Section,
    Sentence,
    SourceFormat,
)
from story_core.models.rag import (
    EMBEDDING_DIMENSIONS,
    Conversation,
    ConversationMessage,
    ParagraphEmbedding,
)
from story_core.models.reading import ReadingPosition, ReadingSession, SpoilerMode
from story_core.models.user import AuthIdentity, IdentityProvider, RefreshToken, User, UserRole, UserStatus

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AudioAsset",
    "AudioKind",
    "AuditLog",
    "AuthIdentity",
    "Base",
    "Book",
    "BookRights",
    "BookStatus",
    "Chapter",
    "Conversation",
    "ConversationMessage",
    "IdentityProvider",
    "Paragraph",
    "ParagraphEmbedding",
    "ReadingPosition",
    "ReadingSession",
    "RefreshToken",
    "Section",
    "Sentence",
    "SourceFormat",
    "SpoilerMode",
    "User",
    "UserRole",
    "UserStatus",
]
