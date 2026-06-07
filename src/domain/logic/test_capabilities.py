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


def test_can_access_network_anon_false():
    assert capabilities.can_access_network(None) is False


def test_can_access_network_unverified_clinician_false():
    assert capabilities.can_access_network(_user(is_verified=True)) is False


def test_can_access_network_verified_clinician_true():
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    assert capabilities.can_access_network(user) is True


def test_can_access_network_ever_verified_no_longer_retains_access():
    """The `ever_verified_at` retention clause was removed — access reverts
    immediately when the underlying claim lapses. A clinician with
    `clinician_verified=False` and only `ever_verified_at` set is denied."""
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
    assert capabilities.can_access_network(user) is False


def test_can_access_network_org_rep_unlocks_for_user_without_clinician():
    """A program coordinator with no Type-1 NPI but a verified org rep
    gets full feed access — handoff §3, §7.1."""
    org = _org(org_verified=True)
    coordinator = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    assert capabilities.can_access_network(coordinator) is True


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


def test_fix_url_for_onboarding_reasons_route_to_step_subroutes():
    assert (
        capabilities.fix_url_for(capabilities.REASON_EMAIL_UNVERIFIED)
        == "/users/me/email/form"
    )


def test_fix_url_for_unknown_reason_falls_back_to_users_me():
    assert capabilities.fix_url_for("totally-not-a-reason") == "/users/me"


def _declared_reasons() -> set[str]:
    reasons = {
        value
        for name, value in vars(capabilities).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert reasons, "no REASON_* constants found"
    return reasons


def test_fix_url_table_covers_every_reason_constant():
    """Guardrail: every REASON_* constant must have a `_REASON_META` entry —
    otherwise the unknown-reason fallback silently masks the missing entry.
    Checked by registry membership, not URL value, since legitimate entries
    (lapsed / additive reasons) may themselves point at the hub root."""
    for reason in _declared_reasons():
        assert (
            reason in capabilities._REASON_META
        ), f"REASON {reason!r} has no entry in _REASON_META"


# ---------- reason_meta ---------------------------------------------------


def test_reason_meta_known_reason_carries_full_copy():
    """A known reason resolves to a title, non-empty unlock copy, a fix
    label, and the same deep-link `fix_url_for` returns — one source for
    every display string."""
    meta = capabilities.reason_meta(capabilities.REASON_NETWORK_UNVERIFIED)
    assert meta.title
    assert meta.unlock
    assert meta.fix_label
    assert meta.fix_url == capabilities.fix_url_for(
        capabilities.REASON_NETWORK_UNVERIFIED
    )


def test_reason_meta_network_unverified_points_at_capability_page():
    """The network-access reason (withheld post detail + locked create CTA)
    carries verification-oriented copy and points at the capability detail
    page where the user can see exactly what needs to change."""
    meta = capabilities.reason_meta(capabilities.REASON_NETWORK_UNVERIFIED)
    assert "Get access" == meta.fix_label
    assert meta.fix_url == "/users/me/access/capabilities/provider-network"
    assert meta.unlock


def test_reason_meta_unknown_reason_falls_back():
    """An unmapped code returns the generic hub pointer, never raises —
    a stray reason renders a sane nudge rather than blank chrome."""
    meta = capabilities.reason_meta("totally-not-a-reason")
    assert meta.fix_url == "/users/me"
    assert meta.unlock
    assert meta.fix_label


def test_reason_meta_covers_every_reason_constant_with_nonempty_copy():
    """Guardrail mirroring the fix-URL one, for the human copy: every
    REASON_* must resolve to non-empty title + unlock + fix_label text so
    no surface renders an empty locked affordance or an untitled card."""
    for reason in _declared_reasons():
        meta = capabilities.reason_meta(reason)
        assert meta.title, f"REASON {reason!r} has empty title"
        assert meta.unlock, f"REASON {reason!r} has empty unlock copy"
        assert meta.fix_label, f"REASON {reason!r} has empty fix_label"


# ---------- check_network -------------------------------------------


def test_check_network_anon_denied():
    """None user: email not verified → entire Bundle fails."""
    check = capabilities.check_network(None)
    assert check.granted is False
    assert check.name == "provider-network"


def test_check_network_email_unverified_denied():
    """Email unverified: Bundle root fails even if a claim would pass."""
    user = _user(
        is_verified=False,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    check = capabilities.check_network(user)
    assert check.granted is False
    # The Condition for email should be unmet.
    email_condition = check.tree.children[0]
    assert email_condition.label_done == "Email verified"
    assert email_condition.met is False


def test_check_network_email_verified_no_claims_denied():
    """Email verified but no clinician or org rep claim → Gate fails."""
    user = _user(is_verified=True)
    check = capabilities.check_network(user)
    assert check.granted is False
    email_condition = check.tree.children[0]
    assert email_condition.met is True
    gate = check.tree.children[1]
    assert gate.met is False


def test_check_network_clinician_verified_granted():
    """Email + clinician_verified → Bundle passes."""
    user = _user(
        is_verified=True,
        clinicians=[_clinician(npi="1234567890", clinician_verified=True)],
    )
    check = capabilities.check_network(user)
    assert check.granted is True
    gate = check.tree.children[1]
    clin_condition = gate.children[0]
    assert clin_condition.label_done == "Clinician identity verified"
    assert clin_condition.met is True


def test_check_network_org_rep_granted():
    """Email + verified org rep → Bundle passes via the Gate's second child."""
    org = _org(org_verified=True)
    user = _user(
        is_verified=True,
        org_representations=[_rep(org_id=org.id, authority_status="verified")],
    )
    check = capabilities.check_network(user)
    assert check.granted is True
    gate = check.tree.children[1]
    org_condition = gate.children[1]
    assert org_condition.label_done == "Organization rep verified"
    assert org_condition.met is True


def test_check_network_fix_urls_present():
    """Unmet Condition nodes carry fix_url links to the canonical resources."""
    user = _user(is_verified=True)  # no claims
    check = capabilities.check_network(user)
    gate = check.tree.children[1]
    clin_condition = gate.children[0]
    org_condition = gate.children[1]
    assert clin_condition.fix_url == "/clinicians/form"
    assert org_condition.fix_url == "/organizations/form"


def test_check_network_tree_structure():
    """The tree is always Bundle > (Condition, Gate > (Condition, Condition))."""
    check = capabilities.check_network(_user())
    assert check.tree.__class__.__name__ == "Bundle"
    assert len(check.tree.children) == 2
    assert check.tree.children[0].__class__.__name__ == "Condition"
    gate = check.tree.children[1]
    assert gate.__class__.__name__ == "Gate"
    assert len(gate.children) == 2
    assert all(c.__class__.__name__ == "Condition" for c in gate.children)


def test_check_network_label_and_description():
    check = capabilities.check_network(_user())
    assert check.tree.label_active == "Provider network"
    assert check.description == "See full provider details and reach out directly."


# ---------- UUID type sanity for claim_state.b ----------------------------


def test_claim_state_b_typed_for_uuids():
    """Phase 2 will populate `b` with org UUIDs. Sanity-check that a
    frozenset of UUIDs is shape-compatible with the dataclass field."""
    org_id = uuid4()
    s = capabilities.ClaimState(a=True, b=frozenset({org_id}))
    assert isinstance(next(iter(s.b)), UUID)
