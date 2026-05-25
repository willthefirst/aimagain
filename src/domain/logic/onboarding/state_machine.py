"""Onboarding wizard state machine.

`next_step(user, *, db)` is the single source of truth for "where does this
user go next in the wizard?" Every wizard route that needs to redirect calls
this function so the truth table lives in one place.

Signal table (read at each dispatch):

| Signal                | Source                                                       |
|-----------------------|--------------------------------------------------------------|
| intent                | user.onboarding_intent                                       |
| has_clinician         | user.providers non-empty (selectin-loaded on User)           |
| clinician_verified    | onboarding clinician's latest Verification.status=='verified'|
| has_opening           | onboarding clinician owns ≥1 OpeningDetail (T4+)            |
| has_reciprocity_profile | clinician has non-empty specialties AND modality (T5+)   |

The "onboarding clinician" is always the most-recently-created Provider owned
by the user. See `onboarding_clinician()`.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import OpeningDetail, Post, Provider, User, Verification

# Stub URL for steps not yet implemented — returns a minimal placeholder page
# until the downstream ticket ships the real page.
_NOT_YET_BUILT = "/welcome/coming-soon"


def onboarding_clinician(user: User) -> Provider | None:
    """Return the most-recently-created Provider owned by `user`, or None.

    All wizard writes target this clinician. Using `created_at` means
    a user who creates a second clinician later gets the wizard routed to the
    new one — intentional; new clinicians need verification too.
    """
    if not user.providers:
        return None
    return max(user.providers, key=lambda p: p.created_at)


async def next_step(user: User, *, db: AsyncSession) -> str:
    """Return the next wizard URL for `user`.

    Pure in the sense that it does not mutate state — it only reads
    signals and returns a URL string. The DB session is needed to check
    verification status (Verifications are not eager-loaded on Provider).
    """
    if user.onboarding_intent is None:
        return "/"

    clinician = onboarding_clinician(user)
    if clinician is None:
        return "/welcome/verify"

    # Check verification status for the onboarding clinician.
    result = await db.execute(
        select(Verification)
        .filter(Verification.provider_id == clinician.id)
        .order_by(Verification.created_at.desc())
        .limit(1)
    )
    latest = result.scalars().first()
    clinician_verified = latest is not None and latest.status == "verified"

    if not clinician_verified:
        return "/welcome/verify"

    # Clinician exists and is verified — branch by intent.
    intent = user.onboarding_intent

    if intent == "refer_now":
        # T5 will replace this stub with /welcome/be-findable
        return _NOT_YET_BUILT

    if intent == "have_openings":
        has_opening_result = await db.execute(
            select(Post)
            .join(OpeningDetail, OpeningDetail.post_id == Post.id)
            .filter(
                Post.kind == "clinician_opening",
                OpeningDetail.provider_id == clinician.id,
            )
            .limit(1)
        )
        has_opening = has_opening_result.scalars().first() is not None
        if not has_opening:
            return "/welcome/first-opening"
        # Terminal: user has completed the wizard. Navigating back to /welcome
        # shows the done page again rather than redirecting to /openings, so
        # the done page is idempotent — clicking "Go to the board" is the
        # natural exit. A session flag would add complexity for minimal gain.
        return "/welcome/done"

    if intent == "building_network":
        # T7 will replace this stub with /welcome/start-network
        return _NOT_YET_BUILT

    if intent == "invited":
        # T7 will replace this stub with /welcome/minimal-profile
        return _NOT_YET_BUILT

    return "/"
