#!/usr/bin/env python3
"""Promote (or revoke) a user's admin status by email.

Idempotent:
  - If the user already has the desired is_superuser value, exits 0 with no change.
  - If the user does not exist, exits non-zero (no auto-create — a typo would
    silently mint a ghost admin).

Run inside the app container. On the dev environment, prefer `dev promote-admin
<email>`. On the production droplet, prefer `./promote-admin <email>` (the
wrapper at deployment/droplet-files/promote-admin.sh).
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from src.db import async_session_maker
from src.models import User


async def set_admin(email: str, revoke: bool) -> int:
    target = not revoke
    verb = "revoke" if revoke else "promote"

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            print(f"❌ No user with email {email}", file=sys.stderr)
            return 1

        if user.is_superuser == target:
            print(f"⏭️  {email} is_superuser already {target} — nothing to {verb}")
            return 0

        user.is_superuser = target
        await session.commit()

        action = "revoked admin from" if revoke else "promoted to admin"
        print(f"✅ {action} {email} (is_superuser={target})")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote or revoke a user's admin status by email.",
    )
    parser.add_argument("email", help="Email address of the user to (de)promote")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke admin status instead of granting it",
    )
    args = parser.parse_args()
    return asyncio.run(set_admin(args.email, args.revoke))


if __name__ == "__main__":
    sys.exit(main())
