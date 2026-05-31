"""Phase-7 tests: the per-kind Claim-A capability gate on post create.

`_assert_post_payload_authz` runs FK-ownership AND the matching
capability check from the two-claim verification model. Per handoff
§4.3 + §7, `referral` and `clinician_opening` require Claim A; a user
who owns the referenced Clinician but isn't `clinician_verified`
should be refused at the payload-authz boundary.

The existing `_assert_post_payload_target_ownership` invariant (own
the FK target row) is exercised in higher-level integration tests;
these tests focus narrowly on the new capability layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.logic.posts.handlers import _assert_post_payload_capability
from src.framework.http.exceptions import ForbiddenError


def _user(
    *,
    is_verified: bool = True,
    clinician_verified: bool = False,
    is_superuser: bool = False,
) -> SimpleNamespace:
    """Stub that satisfies `capabilities.clinician_verified(user)` by
    duck-typing the relevant attributes."""
    clinicians = (
        [SimpleNamespace(clinician_verified=True)] if clinician_verified else []
    )
    return SimpleNamespace(
        id=uuid4(),
        username="t",
        is_superuser=is_superuser,
        is_verified=is_verified,
        clinicians=clinicians,
    )


def _payload(kind: str) -> SimpleNamespace:
    return SimpleNamespace(kind=kind)


def test_referral_create_requires_claim_a():
    """A user without `clinician_verified` is rejected when posting a
    referral — Claim A is the gate."""
    with pytest.raises(ForbiddenError, match="Claim A"):
        _assert_post_payload_capability(_payload("referral"), _user())


def test_referral_create_allowed_for_verified_clinician():
    _assert_post_payload_capability(
        _payload("referral"), _user(clinician_verified=True)
    )


def test_clinician_opening_requires_claim_a():
    with pytest.raises(ForbiddenError, match="Claim A"):
        _assert_post_payload_capability(_payload("clinician_opening"), _user())


def test_clinician_opening_allowed_for_verified_clinician():
    _assert_post_payload_capability(
        _payload("clinician_opening"), _user(clinician_verified=True)
    )


def test_program_intake_capability_deferred_to_phase_5():
    """`program_intake` is intentionally not gated here — the Claim-B
    check requires the program's org id which is a DB read we'd rather
    not add to the payload-authz hook. The Profile Hub PR (Phase 5)
    introduces a dedicated program-intake create path that takes the
    org check; until then this hook lets program_intake through (the
    FK-ownership check still runs upstream)."""
    _assert_post_payload_capability(_payload("program_intake"), _user())


def test_superuser_bypasses_capability_gate():
    """Admins can post any kind regardless of claim state — same
    discipline as the FK-ownership check (superusers bypass)."""
    _assert_post_payload_capability(_payload("referral"), _user(is_superuser=True))


def test_email_unverified_blocks_referral():
    """The capability layer transitively requires `email_verified`
    (because `clinician_verified` requires it). A user whose email is
    unverified can't post a referral even if a stale
    `clinician_verified=True` is on one of their clinicians."""
    user = _user(is_verified=False, clinician_verified=True)
    with pytest.raises(ForbiddenError, match="Claim A"):
        _assert_post_payload_capability(_payload("referral"), user)
