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
    *,
    is_verified: bool = False,
    clinicians: list | None = None,
    org_representations: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        username="test",
        is_verified=is_verified,
        clinicians=clinicians or [],
        org_representations=org_representations or [],
    )


def _clinician(
    *,
    npi: str | None = None,
    clinician_verified: bool = False,
    ever_verified_at=None,
    affiliations: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        npi=npi,
        clinician_verified=clinician_verified,
        ever_verified_at=ever_verified_at,
        # The relationship attribute on `Clinician` is
        # `clinician_affiliations` after the Phase-7-cleanup rename;
        # the keyword arg here keeps the test-author-facing name short
        # but the stub exposes the renamed attribute the predicate
        # reads.
        clinician_affiliations=affiliations or [],
    )


def _org(*, org_verified: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), org_verified=org_verified)


def _rep(
    *,
    org_id,
    authority_status: str = "verified",
    archived_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        org_id=org_id,
        authority_status=authority_status,
        archived_at=archived_at,
    )


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


def test_clinician_verified_clinician_with_npi_but_cache_false():
    """An NPI on file is no longer sufficient; the `clinician_verified`
    denorm cache must also be True (post-NPPES match + license attest)."""
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=False)],
    )
    assert capabilities.clinician_verified(user) is False


def test_clinician_verified_clinician_without_clinician_verified_cache():
    user = _user(is_verified=True, clinicians=[_clinician(npi=None)])
    assert capabilities.clinician_verified(user) is False


def test_clinician_verified_requires_email_verified():
    user = _user(
        is_verified=False,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    assert capabilities.clinician_verified(user) is False


def test_clinician_verified_with_npi():
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    assert capabilities.clinician_verified(user) is True


def test_clinician_verified_any_verified_clinician_suffices():
    """A user can own multiple `Clinician` rows; one with the
    `clinician_verified` cache set is enough."""
    user = _user(
        is_verified=True,
        clinicians=[
            _clinician(npi=None, clinician_verified=False),
            _clinician(npi="9876543210", clinician_verified=True),
        ],
    )
    assert capabilities.clinician_verified(user) is True


# ---------- Claim B (OrgRepresentation-backed) ----------------------------


def test_org_rep_verified_requires_org_verified():
    """Even a verified rep against an unverified org returns False —
    Claim B requires both `Organization.org_verified` and a verified
    `OrgRepresentation` row."""
    org = _org(org_verified=False)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.org_rep_verified(user, org) is False


def test_org_rep_verified_requires_verified_authority_status():
    """A pending or rejected representation does NOT confer Claim B."""
    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="pending")],
    )
    assert capabilities.org_rep_verified(user, org) is False


def test_org_rep_verified_ignores_archived_rows():
    """Per handoff §10.8 archived rows pause authority — they don't
    count toward Claim B."""
    import datetime as _dt

    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[
            _rep(
                org_id=org.id,
                authority_status="verified",
                archived_at=_dt.datetime(2026, 1, 1),
            )
        ],
    )
    assert capabilities.org_rep_verified(user, org) is False


def test_org_rep_verified_happy_path():
    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.org_rep_verified(user, org) is True


def test_org_rep_verified_different_org_id_misses():
    """A verified rep for org A does NOT confer Claim B for org B."""
    other_org = _org(org_verified=True)
    target_org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=other_org.id, authority_status="verified")],
    )
    assert capabilities.org_rep_verified(user, target_org) is False


def test_any_org_rep_verified_true_with_verified_rep():
    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.any_org_rep_verified(user) is True


def test_any_org_rep_verified_false_when_only_pending():
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=uuid4(), authority_status="pending")],
    )
    assert capabilities.any_org_rep_verified(user) is False


def test_any_org_rep_verified_requires_email_verified():
    org = _org(org_verified=True)
    user = _user(
        is_verified=False,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.any_org_rep_verified(user) is False


# ---------- derived gates -------------------------------------------------


def test_can_read_full_feed_anon_false():
    assert capabilities.can_read_full_feed(None) is False


def test_can_read_full_feed_unverified_clinician_false():
    assert capabilities.can_read_full_feed(_user(is_verified=True)) is False


def test_can_read_full_feed_verified_clinician_true():
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    assert capabilities.can_read_full_feed(user) is True


def test_can_read_full_feed_ever_verified_retains_access():
    """Per handoff §7.1: once a user has been verified, they retain
    feed read-access after a regression. A clinician with
    `clinician_verified=False` but `ever_verified_at` set still passes."""
    import datetime as _dt

    user = _user(
        is_verified=True,
        clinicians=[
            _clinician(
                npi="1234567890",
                clinician_verified=False,
                ever_verified_at=_dt.datetime(2026, 1, 1),
            )
        ],
    )
    assert capabilities.can_read_full_feed(user) is True


def test_can_read_full_feed_org_rep_unlocks_for_user_without_clinician():
    """A program coordinator with no Type-1 NPI but a verified org rep
    gets full feed access — handoff §3, §7.1."""
    org = _org(org_verified=True)
    coordinator = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.can_read_full_feed(coordinator) is True


def test_can_post_referral_tracks_clinician_verified():
    verified = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    unverified = _user(is_verified=True)
    assert capabilities.can_post_referral(verified) is True
    assert capabilities.can_post_referral(unverified) is False


def test_can_post_opening_tracks_clinician_verified():
    verified = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    unverified = _user(is_verified=True)
    assert capabilities.can_post_opening(verified) is True
    assert capabilities.can_post_opening(unverified) is False


def test_can_message_tracks_clinician_verified():
    verified = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    assert capabilities.can_message(verified) is True
    assert capabilities.can_message(None) is False


def test_can_post_program_intake_requires_claim_b_for_target_org():
    org = _org(org_verified=True)
    other_org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=other_org.id, authority_status="verified")],
    )
    # Verified rep for `other_org`, but the post targets `org` — denied.
    assert capabilities.can_post_program_intake(user, org) is False
    # Same user posting against `other_org` is allowed.
    assert capabilities.can_post_program_intake(user, other_org) is True


def test_can_post_org_referral_requires_clinician_affiliation():
    """Per handoff §10.5: org-attributed referrals require the target
    clinician to have an active ClinicianAffiliation to the org. Claim B alone
    is not enough — the org must be allowed to speak for the clinician
    in question."""
    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    # Clinician with no affiliation to the target org → denied.
    unaffiliated = _clinician(clinician_verified=True)
    assert capabilities.can_post_org_referral(user, org, unaffiliated) is False

    # Affiliated clinician → allowed.
    affiliated = _clinician(
        clinician_verified=True,
        affiliations=[SimpleNamespace(org_id=org.id)],
    )
    assert capabilities.can_post_org_referral(user, org, affiliated) is True


# ---------- directory_listed ----------------------------------------------


def test_directory_listed_none_false():
    assert capabilities.directory_listed(None) is False


def test_directory_listed_unverified_clinician_false():
    """NPI presence alone is no longer enough; the `clinician_verified`
    denorm cache must be True (post-NPPES + license attest)."""
    assert capabilities.directory_listed(_clinician(npi="1234567890")) is False


def test_directory_listed_verified_clinician_true():
    assert (
        capabilities.directory_listed(
            _clinician(npi="1234567890", clinician_verified=True)
        )
        is True
    )


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
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    s = capabilities.claim_state(user)
    assert s.a is True
    assert s.b == frozenset()
    assert s.lapsed == ()


def test_claim_state_b_only_coordinator():
    """A user with only verified `OrgRepresentation` rows (no clinician)
    lands at `a=False` + `b={org_id, ...}`."""
    org_a = _org(org_verified=True)
    org_b = _org(org_verified=True)
    coordinator = _user(
        is_verified=True,
        org_representations=[
            _rep(org_id=org_a.id, authority_status="verified"),
            _rep(org_id=org_b.id, authority_status="verified"),
        ],
    )
    s = capabilities.claim_state(coordinator)
    assert s.a is False
    assert s.b == frozenset({org_a.id, org_b.id})


def test_claim_state_b_excludes_pending_and_archived():
    """Only verified, non-archived rows count toward `b`."""
    import datetime as _dt

    pending_org = _org(org_verified=True)
    archived_org = _org(org_verified=True)
    active_org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[
            _rep(org_id=pending_org.id, authority_status="pending"),
            _rep(
                org_id=archived_org.id,
                authority_status="verified",
                archived_at=_dt.datetime(2026, 1, 1),
            ),
            _rep(org_id=active_org.id, authority_status="verified"),
        ],
    )
    s = capabilities.claim_state(user)
    assert s.b == frozenset({active_org.id})


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
