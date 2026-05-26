"""Post + detail override — kind discriminator + matching detail.

Posts use a `kind` text column (`referral` / `clinician_opening` /
`program_intake`) plus a 1:1 detail child whose model varies by kind.
The generic generator can't link the parent's `kind` to the right
detail subclass — that's this override.

Per-kind structure:
  - REFERRAL_POST_COUNT × Post(kind='referral') + ReferralDetail
  - OPENING_POST_COUNT  × Post(kind='clinician_opening') + OpeningDetail
  - INTAKE_POST_COUNT   × Post(kind='program_intake') + IntakeDetail

For each kind we generate the detail row via the generic builder (so
new columns on detail tables auto-cover) and then patch a handful of
fields the generic builder can't infer (description templates, FK to
provider/program).

`created_at` is spread across the last 180 days so the listings feed
shows a believable spread.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import (
    IntakeDetail,
    OpeningDetail,
    Post,
    Program,
    Provider,
    ReferralDetail,
    User,
)

from .. import counts
from ..generators import SeedPool, build_row
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import (
    intake_subject,
    opening_subject,
    referral_subject,
    render_intake_description,
    render_opening_description,
    render_referral_description,
)
from . import register


def _shift_created_at(post: Post, days_ago: int) -> None:
    """Match the seed.py:_shift_created_at helper — overrides the
    server_default so the listings page renders a spread of dates."""
    from datetime import datetime, timedelta, timezone

    post.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)


@register(Post)
async def generate_posts(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Post]:
    users: list[User] = pool.all("users")
    providers: list[Provider] = pool.all("providers")
    programs: list[Program] = pool.all("programs")

    out: list[Post] = []

    # --- Referral posts ---
    for i in range(counts.REFERRAL_POST_COUNT):
        post_id = deterministic_uuid("Post", "referral", i)
        post = Post(id=post_id, kind="referral", owner_id=users[i % len(users)].id)
        _shift_created_at(post, days_ago=i % 180)
        detail = build_row(ReferralDetail, i, rng, pool)
        # FK + description: generic builder can't infer either.
        detail.post_id = post_id
        detail.subject = None if rng.bool(0.2) else referral_subject(rng, i)
        detail.description = render_referral_description(rng, i)
        # Sidecar PK isn't an FK-pool target; just give it a stable
        # ID equal to its post_id (post_id is PK on detail).
        post.referral_detail = detail
        merged = await session.merge(post)
        out.append(merged)

    # --- Opening posts ---
    for i in range(counts.OPENING_POST_COUNT):
        post_id = deterministic_uuid("Post", "clinician_opening", i)
        post = Post(
            id=post_id, kind="clinician_opening", owner_id=users[i % len(users)].id
        )
        _shift_created_at(post, days_ago=i % 180)
        detail = build_row(OpeningDetail, i, rng, pool)
        detail.post_id = post_id
        detail.provider_id = providers[i % len(providers)].id
        detail.subject = None if rng.bool(0.2) else opening_subject(rng, i)
        # `description` is nullable — populate most rows for narrative,
        # leave a slice NULL so the empty-state card renders too.
        detail.description = (
            None if rng.bool(0.15) else render_opening_description(rng, i)
        )
        post.opening_detail = detail
        merged = await session.merge(post)
        out.append(merged)

    # --- Intake posts ---
    if programs:
        for i in range(counts.INTAKE_POST_COUNT):
            post_id = deterministic_uuid("Post", "program_intake", i)
            post = Post(
                id=post_id, kind="program_intake", owner_id=users[i % len(users)].id
            )
            _shift_created_at(post, days_ago=i % 180)
            detail = build_row(IntakeDetail, i, rng, pool)
            detail.post_id = post_id
            detail.program_id = programs[i % len(programs)].id
            detail.subject = None if rng.bool(0.2) else intake_subject(rng, i)
            # `description` is nullable — same posture as OpeningDetail.
            detail.description = (
                None if rng.bool(0.15) else render_intake_description(rng, i)
            )
            post.intake_detail = detail
            merged = await session.merge(post)
            out.append(merged)

    await session.commit()
    return out


# Detail tables are owned by `generate_posts` (created inline alongside
# their parent Post). Register no-op overrides so the runner doesn't
# also generate them generically.
@register(ReferralDetail)
async def _noop_referral_detail(rng, pool, session) -> list:
    return pool.all("referral_details")


@register(OpeningDetail)
async def _noop_opening_detail(rng, pool, session) -> list:
    return pool.all("opening_details")


@register(IntakeDetail)
async def _noop_intake_detail(rng, pool, session) -> list:
    return pool.all("intake_details")
