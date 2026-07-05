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
clinician/program).

`created_at` is spread across the last 180 days so the listings feed
shows a believable spread.

Ownership reflects the capability gate for each kind:

  - Referral / opening are *self-path* authored — `can_post_referral` /
    `can_post_opening` require Claim A — so the owner is derived from a
    *verified* listing clinician (`owner_id = clinician.owner_id`). No
    unverified user can end up owning one.
  - Program intake rides Claim B (`can_post_program_intake`), whose seed
    chain (program owner / org rep / org verification) isn't coherent
    yet; intake ownership is a plain non-persona round-robin and is NOT
    capability-correct. Tracked as a follow-up.

Dev personas are excluded from every generic owner pool (an unverified
or clinician-pending persona could never have authored a post); the one
persona that *can* author — the fully-verified one — gets a referral +
opening anchored explicitly against its own clinician. Same exclusion
pattern as `overrides/clinicians.py`; the persona registry is the single
source of truth in `src/domain/routes/dev_personas.py`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import (
    Clinician,
    IntakeDetail,
    OpeningDetail,
    Post,
    Program,
    ReferralDetail,
    User,
)
from src.domain.models.enums import CLIENT_AGE_GROUPS
from src.domain.routes.dev_personas import PERSONAS

from .. import counts
from ..generators import SeedPool, build_row
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import (
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
    clinicians: list[Clinician] = pool.all("clinicians")
    programs: list[Program] = pool.all("programs")

    # Persona users are excluded from the generic round-robin owner pool:
    # a post's owner has to be someone who could actually have authored
    # it, and the unverified / clinician-pending personas hold no
    # publishing capability at all. The verified persona's posts are
    # anchored explicitly at the end of this function. Same exclusion
    # the clinician override applies for `owner_id`.
    persona_emails = {p.email for p in PERSONAS}
    persona_user_ids = {u.id for u in users if u.email in persona_emails}
    owner_users: list[User] = [u for u in users if u.email not in persona_emails]

    # Referral + opening posts are *self-path* authored: the owner is the
    # listing clinician's own owner, who therefore holds Claim A. Drawing
    # the listing clinician from the verified set (excluding persona
    # anchors, whose posts are seeded explicitly below) makes every such
    # post's owner pass `can_post_referral` / `can_post_opening` — an
    # unverified provider can no longer end up owning one. (Program-intake
    # ownership rides Claim B, whose seed chain — program owner, org rep,
    # org verification — isn't coherent yet; tracked separately.)
    verified_clinicians: list[Clinician] = [
        c
        for c in clinicians
        if c.clinician_verified and c.owner_id not in persona_user_ids
    ]

    # Clinician → primary affiliation id. The generic `build_row` would
    # resolve the listing's `clinician_affiliation_id` FK to a *random*
    # affiliation; under the picker-derives-clinician model that must
    # instead be one of the listing clinician's own affiliations. First
    # affiliation seen per clinician is its primary (generate_affiliations
    # appends primary before any secondary), matching
    # `Clinician.primary_clinician_affiliation`.
    primary_aff_by_clinician: dict = {}
    for aff in pool.all("clinician_affiliations"):
        primary_aff_by_clinician.setdefault(aff.clinician_id, aff.id)

    out: list[Post] = []

    # --- Referral posts ---
    for i in range(counts.REFERRAL_POST_COUNT):
        post_id = deterministic_uuid("Post", "referral", i)
        # Owner == the referring clinician's owner (self-path), so the
        # owner necessarily holds Claim A.
        ref_clin = verified_clinicians[i % len(verified_clinicians)]
        post = Post(id=post_id, kind="referral", owner_id=ref_clin.owner_id)
        _shift_created_at(post, days_ago=i % 180)
        detail = build_row(ReferralDetail, i, rng, pool)
        # FK + description: generic builder can't infer either.
        detail.post_id = post_id
        # Referring clinician + its context affiliation, kept coherent:
        # the affiliation must belong to the referring clinician (the
        # picker-derives-clinician invariant).
        detail.referring_clinician_id = ref_clin.id
        detail.clinician_affiliation_id = primary_aff_by_clinician.get(ref_clin.id)
        # A referral describes a single client → exactly one age bucket
        # (the `ck_referral_details_age_groups_single` CHECK + the wire's
        # exactly-one rule). The generic builder draws a multi-element
        # subset; keep its first pick, or draw one when it came back empty.
        detail.age_groups = (
            detail.age_groups[:1]
            if detail.age_groups
            else [rng.choice(CLIENT_AGE_GROUPS)]
        )
        # Referrals have no `subject` column — the title is always derived
        # from demographics (`post_feed_headline`).
        detail.description = render_referral_description(rng, i)
        # Sidecar PK isn't an FK-pool target; just give it a stable
        # ID equal to its post_id (post_id is PK on detail).
        post.referral_detail = detail
        merged = await session.merge(post)
        out.append(merged)

    # --- Opening posts ---
    for i in range(counts.OPENING_POST_COUNT):
        post_id = deterministic_uuid("Post", "clinician_opening", i)
        # Owner == the opening clinician's owner (self-path), so the owner
        # necessarily holds Claim A.
        opening_clin = verified_clinicians[i % len(verified_clinicians)]
        post = Post(
            id=post_id,
            kind="clinician_opening",
            owner_id=opening_clin.owner_id,
        )
        _shift_created_at(post, days_ago=i % 180)
        detail = build_row(OpeningDetail, i, rng, pool)
        detail.post_id = post_id
        detail.clinician_id = opening_clin.id
        # Context affiliation must belong to this opening's clinician.
        detail.clinician_affiliation_id = primary_aff_by_clinician.get(opening_clin.id)
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
            # NOTE: intake ownership should ride Claim B (a verified org
            # rep for the program's org), but the seed's Claim-B chain
            # (program owner / org rep / org verification) isn't coherent
            # yet, so this stays a plain non-persona round-robin. Tracked
            # as a follow-up; do not treat this as capability-correct.
            post = Post(
                id=post_id,
                kind="program_intake",
                owner_id=owner_users[i % len(owner_users)].id,
            )
            _shift_created_at(post, days_ago=i % 180)
            detail = build_row(IntakeDetail, i, rng, pool)
            detail.post_id = post_id
            detail.program_id = programs[i % len(programs)].id
            # `description` is nullable — same posture as OpeningDetail.
            detail.description = (
                None if rng.bool(0.15) else render_intake_description(rng, i)
            )
            post.intake_detail = detail
            merged = await session.merge(post)
            out.append(merged)

    # --- Persona anchor posts ---
    # Only the fully-verified persona (Claim A) can author anything, and
    # only the self-path kinds (referral / opening) — program intake needs
    # Claim B, which no persona holds. Give it one of each so "my posts" /
    # edit / delete flows have content when you log in as it. Owner +
    # referring clinician are kept coherent: the post references the
    # persona's own anchor Clinician (the picker-derives-clinician
    # self-path). Appended after the generic loops so the shared RNG
    # sequence driving the generic dataset is left untouched.
    persona_user_by_email = {u.email: u for u in users}
    clinician_by_owner: dict = {}
    for clinician in clinicians:
        clinician_by_owner.setdefault(clinician.owner_id, clinician)
    for persona in PERSONAS:
        if persona.clinician_verified is not True:
            continue
        user = persona_user_by_email.get(persona.email)
        if user is None:
            continue
        clin = clinician_by_owner.get(user.id)
        if clin is None:
            continue
        aff_id = primary_aff_by_clinician.get(clin.id)

        ref_id = deterministic_uuid("PersonaPost", persona.username, "referral")
        ref_post = Post(id=ref_id, kind="referral", owner_id=user.id)
        _shift_created_at(ref_post, days_ago=3)
        ref_detail = build_row(ReferralDetail, 0, rng, pool)
        ref_detail.post_id = ref_id
        ref_detail.referring_clinician_id = clin.id
        ref_detail.clinician_affiliation_id = aff_id
        ref_detail.age_groups = (
            ref_detail.age_groups[:1]
            if ref_detail.age_groups
            else [rng.choice(CLIENT_AGE_GROUPS)]
        )
        ref_detail.description = render_referral_description(rng, 0)
        ref_post.referral_detail = ref_detail
        out.append(await session.merge(ref_post))

        op_id = deterministic_uuid("PersonaPost", persona.username, "opening")
        op_post = Post(id=op_id, kind="clinician_opening", owner_id=user.id)
        _shift_created_at(op_post, days_ago=5)
        op_detail = build_row(OpeningDetail, 0, rng, pool)
        op_detail.post_id = op_id
        op_detail.clinician_id = clin.id
        op_detail.clinician_affiliation_id = aff_id
        op_detail.description = render_opening_description(rng, 0)
        op_post.opening_detail = op_detail
        out.append(await session.merge(op_post))

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
