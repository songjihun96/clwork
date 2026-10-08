"""Grant or revoke the admin role. Deliberately not exposed over HTTP.

python scripts/set_user_role.py --email someone@example.com --role admin
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from story_core.db.session import create_engine, create_sessionmaker
from story_core.models import AuditLog, User, UserRole

from app.config import Settings
from app.repositories.audit import AuditAction


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    args = parser.parse_args()

    engine = create_engine(Settings().database_options)
    try:
        async with create_sessionmaker(engine)() as session:
            user = await session.scalar(select(User).where(User.email == args.email.strip().lower()))
            if user is None:
                print("user not found", file=sys.stderr)
                return 1
            previous = user.role
            user.role = args.role
            session.add(
                AuditLog(
                    actor_user_id=None,
                    action=AuditAction.USER_ROLE_CHANGED,
                    target_type="user",
                    target_id=str(user.id),
                    details={"from": previous, "to": args.role, "via": "cli"},
                )
            )
            await session.commit()
            print(f"{user.id}: {previous} -> {args.role}")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
