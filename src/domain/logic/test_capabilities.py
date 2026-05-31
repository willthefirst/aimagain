"""Truth-table tests for the capability predicates.

This is the most load-bearing test file in the verification rollout: a
single source of truth for every gate site (routes + templates) is only
useful if its truth table is pinned. Phase 0 ships placeholder predicate
bodies; the table below also serves as the regression line when Phase 2
tightens those bodies against real schema columns — the truth values
must not change for the inputs covered here, only sharpen for inputs
involving `OrgRepresentation` and `ever_verified_at`.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from src.domain.logic import capabilities


def _user(
    *, is_verified: bool = False, clinicians: list | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        username="test",
        is_verified=is_verified,
        clinicians=clinicians or [],
    )


def _clinician(*, npi: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(npi=npi)


# ---------- email_verified ------------------------------------------------


def test_email_verified_anon_false():
    assert capabilities.email_verified(None) is False


def test_email_verified_user_not_verified():
    assert capabilities.email_verified(_user(is_verified=False)) is False


def test_email_verified_user_verified():
    assert capabilities.email_verified(_user(is_verified=True)) is True


def test_email_verified_user_missing_attr_defaults_false():
    """Actor stubs without `is_verified` are treated as not-verified.

    This is the inverse of `base_context()`'s anonymous-defaults-to-True
    rule: that rule keeps the email banner silent for anonymous viewers;
    here, anything that isn't explicitly verified is denied.
    """
    bare = SimpleNamespace(id=uuid4(), is_superuser=False, username="t")
    assert capabilities.email_verified(bare) is False


# ---------- clinician_verified --------------------------------------------


def test_clinician_verified_anon_false():
    assert capabilities.clinician_verified(None) is False


def test_clinician_verified_no_clinicians():
    assert capabilities.clinician_verified(_user(is_verified=True)) is False


def test_clinician_verified_clinician_without_npi():
    user = _user(is_verified=True, clinicians=[_clinician(npi=None)])
    assert capabilities.clinician_verified(user) is False


def test_clinician_verified_requires_email_verified():
    user = _user(is_verified=False, clinicians=[_clinician(npi="1234567890")])
    assert capabilities.clinician_verified(user) is False


def test_clinician_verified_with_npi():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    assert capabilities.clinician_verified(user) is True


def test_clinician_verified_any_clinician_with_npi_suffices():
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi=None), _clinician(npi="9876543210")],
    )
    assert capabilities.clinician_verified(user) is True


# ---------- Claim B placeholders (always False until Phase 1/4) -----------


def test_org_rep_verified_placeholder_false():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    org = SimpleNamespace(id=uuid4())
    assert capabilities.org_rep_verified(user, org) is False


def test_any_org_rep_verified_placeholder_false():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    assert capabilities.any_org_rep_verified(user) is False


# ---------- derived gates -------------------------------------------------


def test_can_read_full_feed_anon_false():
    assert capabilities.can_read_full_feed(None) is False


def test_can_read_full_feed_unverified_clinician_false():
    assert capabilities.can_read_full_feed(_user(is_verified=True)) is False


def test_can_read_full_feed_verified_clinician_true():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    assert capabilities.can_read_full_feed(user) is True


def test_can_post_referral_tracks_clinician_verified():
    verified = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    unverified = _user(is_verified=True)
    assert capabilities.can_post_referral(verified) is True
    assert capabilities.can_post_referral(unverified) is False


def test_can_post_opening_tracks_clinician_verified():
    verified = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    unverified = _user(is_verified=True)
    assert capabilities.can_post_opening(verified) is True
    assert capabilities.can_post_opening(unverified) is False


def test_can_message_tracks_clinician_verified():
    verified = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    assert capabilities.can_message(verified) is True
    assert capabilities.can_message(None) is False


def test_can_post_program_intake_placeholder_false():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    org = SimpleNamespace(id=uuid4())
    assert capabilities.can_post_program_intake(user, org) is False


def test_can_post_org_referral_placeholder_false():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    org = SimpleNamespace(id=uuid4())
    clinician = _clinician(npi="1234567890")
    assert capabilities.can_post_org_referral(user, org, clinician) is False


# ---------- directory_listed ----------------------------------------------


def test_directory_listed_none_false():
    assert capabilities.directory_listed(None) is False


def test_directory_listed_clinician_without_npi_false():
    assert capabilities.directory_listed(_clinician(npi=None)) is False


def test_directory_listed_clinician_with_npi_true():
    assert capabilities.directory_listed(_clinician(npi="1234567890")) is True


# ---------- can_save_favorite (only email_verified) -----------------------


def test_can_save_favorite_anon_false():
    assert capabilities.can_save_favorite(None) is False


def test_can_save_favorite_email_verified_only():
    assert capabilities.can_save_favorite(_user(is_verified=True)) is True
    assert capabilities.can_save_favorite(_user(is_verified=False)) is False


# ---------- claim_state ---------------------------------------------------


def test_claim_state_anon_empty():
    s = capabilities.claim_state(None)
    assert s.a is False
    assert s.b == frozenset()
    assert s.lapsed == ()


def test_claim_state_a_only():
    user = _user(is_verified=True, clinicians=[_clinician(npi="1234567890")])
    s = capabilities.claim_state(user)
    assert s.a is True
    assert s.b == frozenset()
    assert s.lapsed == ()


def test_claim_state_b_set_is_frozenset():
    """The `b` field is a frozenset so the dataclass stays hashable and
    immutable — Phase 5 mode dispatch reads it under
    `if not state.a and not state.b: mode = 'setup'`."""
    s = capabilities.claim_state(None)
    assert isinstance(s.b, frozenset)


# ---------- fix_url_for ---------------------------------------------------


def test_fix_url_for_known_reasons_routes_to_profile_focus():
    assert (
        capabilities.fix_url_for(capabilities.REASON_EMAIL_UNVERIFIED)
        == "/profile?focus=email"
    )
    assert (
        capabilities.fix_url_for(capabilities.REASON_CLAIM_A_UNVERIFIED)
        == "/profile?focus=claim_a"
    )
    assert (
        capabilities.fix_url_for(capabilities.REASON_CLAIM_A_LAPSED)
        == "/profile?focus=claim_a"
    )
    assert (
        capabilities.fix_url_for(capabilities.REASON_CLAIM_B_UNVERIFIED)
        == "/profile?focus=claim_b"
    )
    assert (
        capabilities.fix_url_for(capabilities.REASON_AFFILIATION_MISSING)
        == "/profile?focus=claim_b"
    )


def test_fix_url_for_unknown_reason_falls_back_to_hub_root():
    assert capabilities.fix_url_for("totally-not-a-reason") == "/profile"


def test_fix_url_table_covers_every_reason_constant():
    """Guardrail: every REASON_* constant must have a fix URL mapping —
    otherwise an unknown-reason fallback masks the missing entry."""
    declared_reasons = {
        value
        for name, value in vars(capabilities).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert declared_reasons, "no REASON_* constants found"
    for reason in declared_reasons:
        url = capabilities.fix_url_for(reason)
        assert url != "/profile", f"REASON {reason!r} has no entry in _FIX_URLS"


# ---------- UUID type sanity for claim_state.b ----------------------------


def test_claim_state_b_typed_for_uuids():
    """Phase 2 will populate `b` with org UUIDs. Sanity-check that a
    frozenset of UUIDs is shape-compatible with the dataclass field."""
    org_id = uuid4()
    s = capabilities.ClaimState(a=True, b=frozenset({org_id}))
    assert isinstance(next(iter(s.b)), UUID)
