"""User override — fastapi-users password hashing.

`fastapi-users` owns User creation: it salts/hashes the password,
runs the on_after_register hook, and writes via the `UserManager`.
Direct `session.add(User(...))` would bypass all of that. So the seed
goes through the same manager the HTTP register flow uses.

Idempotency: matched by `email` (the stable deterministic
`clinician_NNN@example.com` shape). First three slots are pinned to
`admin@example.com` / `alice@example.com` / `bob@example.com` so
login muscle memory survives.

`onboarding_intent`: anchor users (first 3) are left NULL — they
represent admin/ops accounts that joined before the field existed.
Every clinician user cycles through the four valid intent values so
the seed satisfies the enum-coverage and nullable-coverage lint checks.
"""

from __future__ import annotations

from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_config import UserManager
from src.domain.logic.users.schema import UserCreate
from src.domain.models import User
from src.domain.models.enums import ONBOARDING_INTENTS

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom
from . import register

SHARED_PASSWORD = "password"

# First three slots — pinned identities. Anything after these is
# `clinician_NNN@example.com` / `clinician_NNN`.
_ANCHOR_USERS: list[dict] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
]


def _fixture_for(index: int) -> dict:
    if index < len(_ANCHOR_USERS):
        return _ANCHOR_USERS[index]
    return {
        "email": f"clinician_{index:03d}@example.com",
        "username": f"clinician_{index:03d}",
        "is_superuser": False,
    }


@register(User)
async def generate_users(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[User]:
    user_db = SQLAlchemyUserDatabase(session, User)
    manager = UserManager(user_db)
    out: list[User] = []
    for index in range(counts.USER_COUNT):
        fixture = _fixture_for(index)
        existing = await session.execute(
            select(User).where(User.email == fixture["email"])
        )
        existing_user = existing.scalar_one_or_none()
        if existing_user is not None:
            out.append(existing_user)
            continue
        user = await manager.create(
            UserCreate(
                email=fixture["email"],
                password=SHARED_PASSWORD,
                username=fixture["username"],
                is_superuser=fixture["is_superuser"],
                is_verified=True,
            ),
            safe=False,
        )
        out.append(user)

    await session.commit()

    # Assign `onboarding_intent` to every clinician user (indexes ≥ 3),
    # cycling through all four valid values. Anchor users (admin / alice /
    # bob) stay NULL — they represent accounts from before the field existed.
    # This satisfies both lint checks: all four enum values are present, and
    # at least one NULL row exists alongside populated rows.
    clinician_users = out[len(_ANCHOR_USERS) :]
    if clinician_users:
        intents = list(ONBOARDING_INTENTS)
        for i, user in enumerate(clinician_users):
            intent = intents[i % len(intents)]
            await session.execute(
                update(User).where(User.id == user.id).values(onboarding_intent=intent)
            )
        await session.commit()
        # Refresh so callers see the updated field.
        for user in clinician_users:
            await session.refresh(user)

    return out
