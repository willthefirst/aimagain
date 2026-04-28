#!/usr/bin/env python3
"""
Seed the database with fixture users for development.

Idempotent: re-running skips users that already exist (matched by email).
All fixture users share the password `password`.
"""

import asyncio
import sys
from typing import TypedDict

# Local import to avoid circulars at module import time
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from src.auth_config import UserManager
from src.db import async_session_maker
from src.models import User
from src.schemas.user import UserCreate

SHARED_PASSWORD = "password"


class FixtureUser(TypedDict):
    email: str
    username: str
    is_superuser: bool


FIXTURE_USERS: list[FixtureUser] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
]


async def seed_users() -> int:
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)

        for fixture in FIXTURE_USERS:
            existing = await session.execute(
                select(User).where(User.email == fixture["email"])
            )
            if existing.scalar_one_or_none() is not None:
                print(f"⏭️  {fixture['email']} already exists, skipping")
                skipped += 1
                continue

            user_create = UserCreate(
                email=fixture["email"],
                password=SHARED_PASSWORD,
                username=fixture["username"],
                is_superuser=fixture["is_superuser"],
                is_verified=True,
            )
            user = await manager.create(user_create, safe=False)
            print(
                f"✅ Created {user.email} "
                f"(username={fixture['username']}, superuser={fixture['is_superuser']})"
            )
            created += 1

        await session.commit()

    print(f"\n🌱 Seed complete: {created} created, {skipped} skipped")
    if created > 0:
        print(f"   Password for all fixture users: {SHARED_PASSWORD}")
    return 0


def main() -> int:
    return asyncio.run(seed_users())


if __name__ == "__main__":
    sys.exit(main())
