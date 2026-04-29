#!/usr/bin/env python3
"""
Seed the database with fixture data for development.

Idempotent:
  - Users are matched by email; existing rows are skipped.
  - Posts are matched by (title, owner_id); existing rows are skipped.

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
from src.models import Post, User
from src.schemas.user import UserCreate

SHARED_PASSWORD = "password"


class FixtureUser(TypedDict):
    email: str
    username: str
    is_superuser: bool


class FixturePost(TypedDict):
    owner_email: str
    title: str
    body: str


FIXTURE_USERS: list[FixtureUser] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
]


FIXTURE_POSTS: list[FixturePost] = [
    {
        "owner_email": "alice@example.com",
        "title": "Hello from Alice",
        "body": "First post — just trying things out.",
    },
    {
        "owner_email": "alice@example.com",
        "title": "On the joy of writing READMEs",
        "body": "Documentation is a love letter to your future self.",
    },
    {
        "owner_email": "bob@example.com",
        "title": "Bob's first post",
        "body": "Hi, I'm Bob. I like long walks and short functions.",
    },
    {
        "owner_email": "admin@example.com",
        "title": "Welcome to Bedlam Connect",
        "body": "Posting is in READ-only mode for now — write endpoints are coming.",
    },
]


async def seed_users() -> tuple[int, int]:
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
                print(f"⏭️  user {fixture['email']} already exists, skipping")
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
                f"✅ Created user {user.email} "
                f"(username={fixture['username']}, superuser={fixture['is_superuser']})"
            )
            created += 1

        await session.commit()

    return created, skipped


async def seed_posts() -> tuple[int, int]:
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_POSTS:
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  post '{fixture['title']}': owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            existing = await session.execute(
                select(Post).where(
                    Post.title == fixture["title"], Post.owner_id == owner.id
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  post '{fixture['title']}' by {fixture['owner_email']} already exists, skipping"
                )
                skipped += 1
                continue

            post = Post(
                title=fixture["title"],
                body=fixture["body"],
                owner_id=owner.id,
            )
            session.add(post)
            print(f"✅ Created post '{fixture['title']}' by {fixture['owner_email']}")
            created += 1

        await session.commit()

    return created, skipped


async def seed_all() -> int:
    users_created, users_skipped = await seed_users()
    posts_created, posts_skipped = await seed_posts()

    print(
        f"\n🌱 Seed complete:"
        f" {users_created} users created ({users_skipped} skipped),"
        f" {posts_created} posts created ({posts_skipped} skipped)"
    )
    if users_created > 0:
        print(f"   Password for all fixture users: {SHARED_PASSWORD}")
    return 0


def main() -> int:
    return asyncio.run(seed_all())


if __name__ == "__main__":
    sys.exit(main())
