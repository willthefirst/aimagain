"""Tests for the onboarding step registry.

Pins that the itemized checklist tracks the `capabilities` predicates
exactly (so the banner / `/profile` rows can't disagree with the post
gate), that the spine is ordered email -> identity, and that the two-claim
OR collapses into one `identity` step satisfied by Claim A *or* Claim B.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.domain.logic import capabilities
from src.domain.logic.profile.onboarding import (
    ONBOARDING_STEPS,
    onboarding_checklist,
)


def _user(*, email=True, claim_a=False, claim_b=False, ever_verified=False):
    """Duck-typed user matching what `capabilities.*` reads."""
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


def test_spine_is_ordered_email_then_identity():
    assert [s.key for s in ONBOARDING_STEPS] == ["email", "identity"]


def test_step_action_href_derives_from_reason():
    # The deep-link vocab lives in capabilities, not duplicated on the row.
    for step in ONBOARDING_STEPS:
        assert step.action_href == capabilities.fix_url_for(step.reason)


def test_no_claim_no_email_both_steps_incomplete_next_is_email():
    c = onboarding_checklist(_user(email=False))
    assert [s.complete for s in c.statuses] == [False, False]
    assert c.next_step.key == "email"
    assert c.complete is False
    assert c.incomplete is True


def test_email_only_identity_remains():
    c = onboarding_checklist(_user(email=True))
    statuses = {s.step.key: s.complete for s in c.statuses}
    assert statuses == {"email": True, "identity": False}
    assert c.next_step.key == "identity"
    assert c.complete is False


def test_claim_a_completes_identity():
    c = onboarding_checklist(_user(claim_a=True))
    assert {s.step.key: s.complete for s in c.statuses} == {
        "email": True,
        "identity": True,
    }
    assert c.next_step is None
    assert c.complete is True


def test_claim_b_alone_completes_identity():
    # The OR: an org rep with no Claim A still clears the identity step.
    c = onboarding_checklist(_user(claim_b=True))
    assert {s.step.key: s.complete for s in c.statuses}["identity"] is True
    assert c.complete is True


def test_email_floor_gates_identity():
    # Without verified email, Claim A reads false (capabilities floor), so
    # identity cannot complete even with a "verified" clinician row.
    c = onboarding_checklist(_user(email=False, claim_a=True))
    assert {s.step.key: s.complete for s in c.statuses} == {
        "email": False,
        "identity": False,
    }
    assert c.next_step.key == "email"


def test_lapsed_clinician_identity_incomplete():
    # ever_verified retains feed read elsewhere, but the identity step
    # tracks *current* posting capability, so it reads incomplete.
    c = onboarding_checklist(_user(claim_a=False, ever_verified=True))
    assert {s.step.key: s.complete for s in c.statuses}["identity"] is False
    assert c.complete is False
