#!/usr/bin/env python3
"""
Seed the database with fixture data for development.

Idempotent:
  - Users are matched by email; existing rows are skipped.
  - Provider-availability posts are matched by
    (kind='provider_availability', owner_id, practice_name); existing
    rows are skipped.

All fixture users share the password `password`.
"""

import asyncio
import sys
from typing import Any, TypedDict

# Local import to avoid circulars at module import time
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from src.auth_config import UserManager
from src.db import async_session_maker
from src.domain.logic.users.schema import UserCreate
from src.domain.models import Post, ProviderAvailabilityDetail, User

SHARED_PASSWORD = "password"


class FixtureUser(TypedDict):
    email: str
    username: str
    is_superuser: bool


class FixtureProviderAvailability(TypedDict):
    owner_email: str
    detail: dict[str, Any]


FIXTURE_USERS: list[FixtureUser] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
]


# Real-world canonical examples that drive the schema-evolution work in
# the issue series spawned by #420. Each `TODO(issue-N)` marker pins a
# cell that doesn't fit today's schema and points at the follow-on PR
# that will reshape both schema and seed together. Removing a marker
# without that schema change is a regression — the markers are the
# series' breadcrumb trail.
FIXTURE_PROVIDER_AVAILABILITY: list[FixtureProviderAvailability] = [
    {
        "owner_email": "alice@example.com",
        "detail": {
            "practice_name": "Katie Reeves, PhD",
            "available_providers": "Katie Reeves, PhD",
            # TODO(issue-5): telehealth-only — no city/zip. Required today; relax in #5.
            "location_city": "(telehealth only)",
            "location_state": "CA",
            "location_zip": "00000",  # TODO(issue-5): placeholder; required today.
            "in_person_sessions": "no",
            "virtual_sessions": "yes",
            "desired_times": [],
            "services": ["psychotherapy", "medication_management"],
            "settings": ["outpatient"],
            "treatment_modality": "Psychodynamic, control-mastery",
            # TODO(issue-2): the lead pitch ("immediate availability for new
            # patients...") belongs in `description`, not `client_focus`. Folded
            # for now.
            "client_focus": (
                "Older teens / TAY with ADHD, anxiety, depression, self-harm, "
                "suicidality. Immediate availability for new patients; 25-min "
                "(med management only) or 50-min sessions."
            ),
            # TODO(issue-4): spans adolescents + young_adults + adults. Single-valued today.
            "age_group": "adolescents_14_18",
            "non_english_services": "no",  # TODO(issue-3): replace with languages=["en"].
            # TODO(issue-6): true value is self_pay_only; not in vocab today.
            # Best-fit placeholder.
            "payment_situation": "out_of_network",
            "sliding_scale": False,
            "cost": "$250 - $600 per session",
            # TODO(issue-2): website=katiereevesphd.com
            # TODO(issue-2): referral_instructions
        },
    },
    {
        "owner_email": "alice@example.com",
        "detail": {
            "practice_name": "Camp BooHoo",
            # TODO(issue-9): may drop available_providers.
            "available_providers": "Camp BooHoo staff",
            "location_city": "Santa Clara",
            "location_state": "CA",
            # TODO(issue-5): venue (fairgrounds) has no zip; required today.
            "location_zip": "95050",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "desired_times": [],
            # TODO(issue-7): "therapeutic camp" doesn't fit; allied_health is closest.
            "services": ["allied_health"],
            # TODO(issue-7): day_program token not in vocab yet. Outpatient is closest.
            "settings": ["outpatient"],
            "treatment_modality": "Social skills, emotion regulation",
            # TODO(issue-2): the camp pitch belongs in description.
            "client_focus": (
                "Middle schoolers with ASD focused on social skills and "
                "emotion regulation."
            ),
            # TODO(issue-4): middle school spans children_6_10 + preteens_11_13.
            "age_group": "preteens_11_13",
            "non_english_services": "yes",  # TODO(issue-3): replace with languages=["en", "es"].
            "payment_situation": "out_of_network",  # TODO(issue-6): true value is self_pay_only.
            "sliding_scale": True,
            "cost": "$2,500 / session",
            # TODO(issue-2): website=boohoocrybaby.com
            # TODO(issue-2): referral_instructions
            # TODO(issue-8): cohort dates ("May 25 & Jun 18, 2-week sessions, M-F 9-5")
        },
    },
    {
        "owner_email": "alice@example.com",
        "detail": {
            "practice_name": "RISE IOP at CHC",
            "available_providers": "RISE program staff",
            "location_city": "Palo Alto",
            "location_state": "CA",
            "location_zip": "94304",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "desired_times": [],
            # TODO(issue-7): peer + family groups not in vocab yet
            # (group_therapy, family_therapy).
            "services": ["psychotherapy", "medication_management"],
            "settings": ["iop"],
            "treatment_modality": "Comprehensive DBT",
            # TODO(issue-2): the IOP pitch belongs in description.
            "client_focus": (
                "High school students with high acuity, including "
                "self-harm/suicidality with no immediate risk of harm to self "
                "or others."
            ),
            # TODO(issue-4): "high school" spans adolescents_14_18 + possibly
            # young_adults_19_24.
            "age_group": "adolescents_14_18",
            "non_english_services": "yes",  # TODO(issue-3): replace with languages=["en", "es"].
            # TODO(issue-6): true value is please_contact
            # ("Yes — no MediCal, please contact").
            "payment_situation": "in_network",
            "sliding_scale": True,
            "cost": "$4k/week",
            # TODO(issue-2): website=CHC.rise.org
            # TODO(issue-2): referral_instructions
            # TODO(issue-8): "M-F 8:30am-4:30pm, starts May 11"
        },
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


async def seed_provider_availability() -> tuple[int, int]:
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_PROVIDER_AVAILABILITY:
            practice_name = fixture["detail"]["practice_name"]
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  PA post '{practice_name}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            existing = await session.execute(
                select(Post)
                .join(
                    ProviderAvailabilityDetail,
                    ProviderAvailabilityDetail.post_id == Post.id,
                )
                .where(
                    Post.kind == "provider_availability",
                    Post.owner_id == owner.id,
                    ProviderAvailabilityDetail.practice_name == practice_name,
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  PA post '{practice_name}' by {fixture['owner_email']} "
                    f"already exists, skipping"
                )
                skipped += 1
                continue

            post = Post(kind="provider_availability", owner_id=owner.id)
            post.provider_availability_detail = ProviderAvailabilityDetail(
                **fixture["detail"]
            )
            session.add(post)
            print(f"✅ Created PA post '{practice_name}' by {fixture['owner_email']}")
            created += 1

        await session.commit()

    return created, skipped


async def seed_all() -> int:
    users_created, users_skipped = await seed_users()
    pa_created, pa_skipped = await seed_provider_availability()

    print(
        f"\n🌱 Seed complete:"
        f" {users_created} users created ({users_skipped} skipped),"
        f" {pa_created} provider-availability posts created ({pa_skipped} skipped)"
    )
    if users_created > 0:
        print(f"   Password for all fixture users: {SHARED_PASSWORD}")
    return 0


def main() -> int:
    return asyncio.run(seed_all())


if __name__ == "__main__":
    sys.exit(main())
