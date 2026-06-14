"""User override — fastapi-users password hashing.

`fastapi-users` owns User creation: it salts/hashes the password,
runs the on_after_register hook, and writes via the `UserManager`.
Direct `session.add(User(...))` would bypass all of that. So the seed
goes through the same manager the HTTP register flow uses.

Idempotency: matched by `email` (the stable deterministic
`clinician_NNN@example.com` shape). The leading anchor slots are
pinned so login muscle memory survives — see ``_ANCHOR_USERS`` below.
"""

from __future__ import annotations

from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_config import UserManager
from src.domain.logic.users.schema import UserCreate
from src.domain.models import User
from src.domain.routes.dev_personas import PERSONAS

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom
from . import register

SHARED_PASSWORD = "password"

# Pinned anchor slots — anything after these is the deterministic
# `clinician_NNN@example.com` / `clinician_NNN` shape.
#
# Slot 0: the admin superuser. Slots 1+: persona anchors, sourced from
# the single-source-of-truth registry in
# `src/domain/routes/dev_personas.py` so adding or renaming a persona
# only touches that file.
_ANCHOR_USERS: list[dict] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    *(
        {
            "email": p.email,
            "username": p.username,
            "is_superuser": False,
            "is_verified": p.is_verified,
        }
        for p in PERSONAS
    ),
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
        # `is_verified` defaults to True for every seed user except the
        # `unverified@example.com` persona, which exercises the
        # "verify your email" nag-banner code path. Whatever we pass
        # here sticks: `UserManager.on_after_register` only auto-verifies
        # when a `Request` is present (i.e. browser-initiated
        # registration), so programmatic callers like this one own
        # `is_verified` directly via `UserCreate`.
        user = await manager.create(
            UserCreate(
                email=fixture["email"],
                password=SHARED_PASSWORD,
                username=fixture["username"],
                is_superuser=fixture["is_superuser"],
                is_verified=fixture.get("is_verified", True),
            ),
            safe=False,
        )
        out.append(user)
    await session.commit()
    return out
