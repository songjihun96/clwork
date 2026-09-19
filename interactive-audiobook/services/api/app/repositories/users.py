import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from story_core.models.user import AuthIdentity, IdentityProvider, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_identity(self, provider: IdentityProvider, subject: str) -> User | None:
        result = await self._session.execute(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.provider == provider, AuthIdentity.subject == subject)
        )
        return result.scalar_one_or_none()

    async def add(self, user: User) -> None:
        # Flush immediately: without relationship() the unit of work does not order inserts by
        # foreign key, so the users row must exist before dependent rows are added.
        # Raises IntegrityError on a duplicate email.
        self._session.add(user)
        await self._session.flush()

    async def add_identity(self, identity: AuthIdentity) -> None:
        self._session.add(identity)
        await self._session.flush()

    async def delete(self, user_id: uuid.UUID) -> None:
        # Dependent rows are removed by ON DELETE CASCADE in the database.
        await self._session.execute(delete(User).where(User.id == user_id))
