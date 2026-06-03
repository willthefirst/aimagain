"""Tests for `onboarding_readiness` — the compact readiness projection.

Pins that the summary tracks the `capabilities` predicates exactly (so a
"Getting started" checklist can't disagree with the post gate) and that
`next_label`/`next_href` walk the verification ladder in order: email →
identity → done.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.domain.logic.profile.view import onboarding_readiness


def _user(*, email=True, claim_a=False, claim_b=False, ever_verified=False):
    """Duck-typed user matching what `capabilities.*` reads:
    `is_verified` (email), `clinicians[*].clinician_verified` /
    `.ever_verified_at` (Claim A / retention), `org_representations`
    (Claim B)."""
    clinicians = []
    if claim_a or ever_verified:
        clinicians = [
            SimpleNamespace(
                clinician_verified=claim_a,
                ever_verified_at=("2026-01-01" if ever_verified else None),
            )
        ]
    reps = (
        [SimpleNamespace(authority_status="verified", archived_at=None)]
        if claim_b
        else []
    )
    return SimpleNamespace(
        is_verified=email,
        clinicians=clinicians,
        org_representations=reps,
    )


def test_unverified_email_blocks_everything_and_points_at_email():
    r = onboarding_readiness(_user(email=False, claim_a=True))
    assert r.email_verified is False
    # Email is the floor — Claim A reads false without it.
    assert r.claim_a_verified is False
    assert r.can_post is False
    assert r.next_label == "Verify your email"
    assert r.next_href == "/profile/email"


def test_email_verified_no_claim_points_at_identity():
    r = onboarding_readiness(_user(email=True))
    assert r.email_verified is True
    assert r.can_post is False
    assert r.next_label == "Verify your identity to start posting"
    assert r.next_href == "/profile/identity"


def test_claim_a_unlocks_posting_and_clears_next_step():
    r = onboarding_readiness(_user(claim_a=True))
    assert r.claim_a_verified is True
    assert r.can_post is True
    assert r.can_read_full_feed is True
    assert r.next_label is None
    assert r.next_href is None


def test_claim_b_alone_unlocks_posting():
    r = onboarding_readiness(_user(claim_b=True))
    assert r.claim_a_verified is False
    assert r.claim_b_verified is True
    assert r.can_post is True
    assert r.next_label is None


def test_lapsed_clinician_retains_feed_but_cannot_post():
    """Once-verified (ever_verified_at set) but not currently verified:
    full-feed read is retained, but posting is not — the projection
    surfaces the identity next-step again (the `/profile/identity` subroute,
    where the re-verification flow lives)."""
    r = onboarding_readiness(_user(claim_a=False, ever_verified=True))
    assert r.can_read_full_feed is True
    assert r.can_post is False
    assert r.next_href == "/profile/identity"
