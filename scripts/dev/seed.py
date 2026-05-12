#!/usr/bin/env python3
"""
Seed the database with fixture data for development.

Idempotent:
  - Users are matched by email; existing rows are skipped.
  - Providers are matched by (owner_id, practice_name); existing rows
    are reused so PA fixtures can always point at a real Provider.
  - Provider-availability posts are matched by
    (kind='provider_availability', owner_id, provider_id); existing
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
from src.domain.models import Post, Provider, ProviderAvailabilityDetail, User

SHARED_PASSWORD = "password"


class FixtureUser(TypedDict):
    email: str
    username: str
    is_superuser: bool


class FixtureProviderAvailability(TypedDict):
    owner_email: str
    provider: dict[str, Any]
    detail: dict[str, Any]


FIXTURE_USERS: list[FixtureUser] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
]


# Real-world canonical examples that drive the schema-evolution work in
# the issue series spawned by #420. Each fixture now declares its
# Provider profile (practice + location + delivery format) alongside
# the PA announcement (#448). The seed creates/reuses the Provider,
# then points the PA's `provider_id` at it.
FIXTURE_PROVIDER_AVAILABILITY: list[FixtureProviderAvailability] = [
    {
        "owner_email": "alice@example.com",
        "provider": {
            "practice_name": "Katie Reeves, PhD",
            # Telehealth-only practice — no city/ZIP in the source
            # example. The Provider model still requires these fields,
            # so we record placeholders documenting the telehealth
            # posture; the announcement narrative covers the real
            # delivery context.
            "location_city": "(telehealth)",
            "location_state": "CA",
            "location_zip": "00000",
            "in_person_sessions": "no",
            "virtual_sessions": "yes",
            "accepts_in_network": False,
            "accepts_out_of_network": False,
            "in_network_carriers": [],
            "sliding_scale": False,
            "cost": "$250 - $600 per session",
        },
        "detail": {
            "description": (
                "Solo private practice offering psychotherapy and medication "
                "management for older teens and transitional-age youth with "
                "ADHD, anxiety, depression, self-harm, and suicidality. "
                "Immediate availability for new patients. 25-minute med-"
                "management visits and 50-minute therapy sessions."
            ),
            "referral_instructions": "Contact via website to schedule an intake call.",
            "website": "https://katiereevesphd.com",
            "desired_times": [],
            "services": ["psychotherapy", "medication_management"],
            "settings": ["outpatient"],
            "treatment_modality": "Psychodynamic, control-mastery",
            "age_groups": [
                "adolescents_14_18",
                "young_adults_19_24",
                "adults_25_64",
            ],
            "languages": ["en"],
        },
    },
    {
        "owner_email": "alice@example.com",
        "provider": {
            "practice_name": "Camp BooHoo",
            "location_city": "Santa Clara",
            "location_state": "CA",
            # Venue (fairgrounds) has no specific ZIP — keep the
            # county-seat ZIP as a serviceable placeholder so the
            # Provider's NOT NULL constraint stays satisfied; the
            # narrative carries the real location info.
            "location_zip": "95050",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "accepts_in_network": False,
            "accepts_out_of_network": False,
            "in_network_carriers": [],
            "sliding_scale": True,
            "cost": "$2,500 / session",
        },
        "detail": {
            "description": (
                "Therapeutic summer camp focused on social skills and emotion "
                "regulation for middle schoolers with ASD. Two 2-week cohorts "
                "(May 25 and Jun 18), M-F 9am-5pm at the Santa Clara County "
                "Fairgrounds."
            ),
            "referral_instructions": (
                "Visit our website to download the intake packet, then email "
                "campbooohoo@example.com to reserve a cohort spot."
            ),
            "website": "https://boohoocrybaby.com",
            "desired_times": [],
            "schedule_text": "May 25 & Jun 18 cohorts; 2-week sessions; M-F 9am–5pm",
            "services": ["group_therapy"],
            "settings": ["day_program"],
            "treatment_modality": "Social skills, emotion regulation",
            "age_groups": ["children_6_10", "preteens_11_13"],
            "languages": ["en", "es"],
        },
    },
    {
        "owner_email": "alice@example.com",
        "provider": {
            "practice_name": "RISE IOP at CHC",
            "location_city": "Palo Alto",
            "location_state": "CA",
            "location_zip": "94304",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            # Source says "no MediCal, please contact for carriers" — the
            # carrier list itself is in `referral_instructions`. Use
            # `other` as a placeholder so the in-network invariant
            # (min-1 carrier when accepting in-network) holds.
            "accepts_in_network": True,
            "accepts_out_of_network": True,
            "in_network_carriers": ["other"],
            "sliding_scale": True,
            "cost": "$4k/week",
        },
        "detail": {
            "description": (
                "RISE is a Comprehensive DBT intensive outpatient program for "
                "high school students with high acuity, including those with "
                "self-harm or suicidality at no immediate risk of harm to self "
                "or others. Two last-minute openings; new cohort starts May 11. "
                "M-F 8:30am-4:30pm."
            ),
            "referral_instructions": (
                "Please contact the program coordinator for intake details."
            ),
            "website": "https://chc.rise.org",
            "desired_times": [],
            "schedule_text": "M-F 8:30am–4:30pm; current cohort starts May 11",
            "services": [
                "psychotherapy",
                "medication_management",
                "group_therapy",
                "family_therapy",
            ],
            "settings": ["iop"],
            "treatment_modality": "Comprehensive DBT",
            "age_groups": ["adolescents_14_18"],
            "languages": ["en", "es"],
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
    providers_created = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_PROVIDER_AVAILABILITY:
            practice_name = fixture["provider"]["practice_name"]
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

            # Find-or-create the Provider for this fixture's owner +
            # practice_name. Reusing across reseeds keeps the FK stable.
            provider_result = await session.execute(
                select(Provider).where(
                    Provider.owner_id == owner.id,
                    Provider.practice_name == practice_name,
                )
            )
            provider = provider_result.scalar_one_or_none()
            if provider is None:
                provider = Provider(owner_id=owner.id, **fixture["provider"])
                session.add(provider)
                await session.flush()
                providers_created += 1
                print(
                    f"✅ Created provider '{practice_name}' "
                    f"for {fixture['owner_email']}"
                )

            existing = await session.execute(
                select(Post)
                .join(
                    ProviderAvailabilityDetail,
                    ProviderAvailabilityDetail.post_id == Post.id,
                )
                .where(
                    Post.kind == "provider_availability",
                    Post.owner_id == owner.id,
                    ProviderAvailabilityDetail.provider_id == provider.id,
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
                provider_id=provider.id, **fixture["detail"]
            )
            session.add(post)
            print(f"✅ Created PA post '{practice_name}' by {fixture['owner_email']}")
            created += 1

        await session.commit()

    if providers_created:
        print(f"   ({providers_created} provider profiles created)")
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
