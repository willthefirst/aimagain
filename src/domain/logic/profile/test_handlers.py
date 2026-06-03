"""Tests for the Profile Hub mode dispatch.

`resolve_profile_mode` is a pure function of the user's `ClaimState`
(no DB reads, no `setup_goals` column — the goal-picker is
recomputed each load per the design trade-off resolved during plan
mode).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.domain.logic.profile.handlers import (
    MODE_ADD_CLAIM,
    MODE_MANAGE,
    MODE_REVERIFY,
    MODE_SETUP,
    PROFILE_MODES,
    build_profile_context,
    resolve_profile_mode,
)


def _user(
    *,
    is_verified: bool = True,
    clinicians: list | None = None,
    org_representations: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        username="alice",
        is_superuser=False,
        is_verified=is_verified,
        clinicians=clinicians or [],
        org_representations=org_representations or [],
    )


def _clinician(*, clinician_verified: bool = False, ever_verified_at=None):
    return SimpleNamespace(
        id=uuid4(),
        npi="1234567890",
        clinician_verified=clinician_verified,
        ever_verified_at=ever_verified_at,
        affiliations=[],
    )


def _rep(*, authority_status: str = "verified"):
    return SimpleNamespace(
        org_id=uuid4(),
        authority_status=authority_status,
        archived_at=None,
    )


def test_no_claim_user_lands_in_setup():
    assert resolve_profile_mode(_user()) == MODE_SETUP


def test_verified_clinician_lands_in_manage():
    user = _user(clinicians=[_clinician(clinician_verified=True)])
    assert resolve_profile_mode(user) == MODE_MANAGE


def test_org_rep_only_user_lands_in_manage():
    """Per handoff §5 / wireframe L5: a coordinator with no Type-1 NPI
    but verified Claim B reaches manage mode without ever passing
    through setup."""
    user = _user(org_representations=[_rep()])
    assert resolve_profile_mode(user) == MODE_MANAGE


def test_add_claim_intent_routes_to_add_claim_when_verified():
    """The `?intent=add_claim` query-string param (set by the
    "Add a capability" CTA) routes a verified user to add-a-claim mode
    instead of manage."""
    user = _user(clinicians=[_clinician(clinician_verified=True)])
    assert resolve_profile_mode(user, intent="add_claim") == MODE_ADD_CLAIM


def test_add_claim_intent_ignored_when_no_claims():
    """A user with no claims at all still lands in `setup` even if the
    URL includes `?intent=add_claim` — there's nothing to add ON TOP
    of yet. The hub re-derives mode from claim state; the intent is a
    routing hint, not an override."""
    assert resolve_profile_mode(_user(), intent="add_claim") == MODE_SETUP


def test_profile_modes_constant_matches_module_constants():
    """Cross-check that the `PROFILE_MODES` tuple exposed for templates
    stays in lockstep with the individual constants — a missing entry
    here would silently drop a mode from a `{% for m in profile_modes %}`
    rendering."""
    assert set(PROFILE_MODES) == {
        MODE_SETUP,
        MODE_MANAGE,
        MODE_ADD_CLAIM,
        MODE_REVERIFY,
    }


def test_lapsed_claim_routes_to_re_verify():
    """If `ClaimState.lapsed` is non-empty, mode flips to `re-verify`
    even when Claim A or Claim B is still partially live — the wireframe
    L7 banner needs a dedicated mode so the partial can highlight which
    capabilities are paused. Phase 5 doesn't yet populate `lapsed` (the
    recompute helpers in Phase 3 left it empty until the re-verify
    detection lands); this test pins the dispatch so when `lapsed`
    starts firing, the mode flip is automatic."""
    user = _user(clinicians=[_clinician(clinician_verified=True)])
    # Inject a synthetic lapsed reason via a stub claim_state — calling
    # resolve_profile_mode indirectly through monkeypatching would be
    # heavier than just confirming the rule reads `state.lapsed` first.
    from src.domain.logic import capabilities

    original = capabilities.claim_state
    try:
        capabilities.claim_state = lambda u: capabilities.ClaimState(
            a=True, b=frozenset(), lapsed=("claim_a_lapsed",)
        )
        assert resolve_profile_mode(user) == MODE_REVERIFY
    finally:
        capabilities.claim_state = original


def test_build_profile_context_exposes_mode_and_lists():
    user = _user(
        clinicians=[_clinician(clinician_verified=True)],
        org_representations=[_rep()],
    )
    ctx = build_profile_context(user)
    assert ctx["mode"] == MODE_MANAGE
    assert ctx["clinicians"] == user.clinicians
    assert ctx["org_representations"] == user.org_representations
    assert ctx["claim_state"].a is True
    assert len(ctx["claim_state"].b) == 1
    # A verified user has cleared the spine — the progress overview reads
    # complete (and `_checklist.html` therefore renders nothing).
    assert ctx["checklist"].complete is True


def test_build_profile_context_checklist_marks_remaining_steps():
    """A no-claim user's checklist surfaces the email-complete /
    identity-pending split the `/profile` progress strip renders."""
    user = _user(is_verified=True, clinicians=[], org_representations=[])
    checklist = build_profile_context(user)["checklist"]
    by_key = {s.step.key: s.complete for s in checklist.statuses}
    assert by_key == {"email": True, "identity": False}
    assert checklist.incomplete is True
    assert checklist.next_step.key == "identity"


# ---------------------------------------------------------------------------
# Non-clinician org-rep onboarding path
# ---------------------------------------------------------------------------


def test_non_clinician_org_rep_only_exits_setup():
    """A user with a verified OrgRepresentation but no clinician exits setup
    into manage mode — the two-claim model allows Claim B without Claim A."""
    user = _user(org_representations=[_rep(authority_status="verified")])
    assert resolve_profile_mode(user) == MODE_MANAGE


def test_pending_org_rep_stays_in_setup():
    """An OrgRepresentation that is still `pending` does not contribute to
    `claim_state.b`, so the user stays in setup mode."""
    user = _user(org_representations=[_rep(authority_status="pending")])
    assert resolve_profile_mode(user) == MODE_SETUP


def test_archived_org_rep_stays_in_setup():
    """An archived OrgRepresentation (revoked) is excluded from the active rep
    set, so the user falls back to setup mode if they have no other claims."""
    from datetime import datetime
    from types import SimpleNamespace

    archived_rep = SimpleNamespace(
        org_id=uuid4(),
        authority_status="verified",
        archived_at=datetime.now(),
    )
    user = _user(org_representations=[archived_rep])
    assert resolve_profile_mode(user) == MODE_SETUP


# ---------------------------------------------------------------------------
# _assert_clinician_payload_org_ownership return value
# ---------------------------------------------------------------------------


async def test_clinician_create_handler_uses_practice_name():
    """_assert_clinician_payload_org_ownership should use practice_name over
    first+last when it is provided, so the auto-org gets the right display name."""
    from types import SimpleNamespace

    from src.domain.logic.clinicians.handlers import (
        _assert_clinician_payload_org_ownership,
    )

    class _MockRepo:
        last_created = None

        async def create(self, obj):
            self.__class__.last_created = obj
            obj.id = uuid4()
            return obj

        async def get_by_model_id(self, *a, **kw):
            return None

    user = SimpleNamespace(
        id=uuid4(), username="alice", is_superuser=False, is_verified=True
    )

    class _Payload:
        solo_practice = True
        practice_name = "Single Thread Psychiatry"
        first_name = "Katie"
        last_name = "Reeves"
        org_id = None

    repo = _MockRepo()
    result = await _assert_clinician_payload_org_ownership(
        payload=_Payload(),
        requesting_user=user,
        organization_repo=repo,
    )
    assert result is not None
    assert _MockRepo.last_created.name == "Single Thread Psychiatry"


async def test_clinician_create_handler_falls_back_to_name():
    """When practice_name is absent, the org name falls back to first+last."""
    from types import SimpleNamespace

    from src.domain.logic.clinicians.handlers import (
        _assert_clinician_payload_org_ownership,
    )

    class _MockRepo:
        last_created = None

        async def create(self, obj):
            self.__class__.last_created = obj
            obj.id = uuid4()
            return obj

    user = SimpleNamespace(
        id=uuid4(), username="alice", is_superuser=False, is_verified=True
    )

    class _Payload:
        solo_practice = True
        practice_name = None
        first_name = "Katie"
        last_name = "Reeves"
        org_id = None

    await _assert_clinician_payload_org_ownership(
        payload=_Payload(),
        requesting_user=user,
        organization_repo=_MockRepo(),
    )
    assert _MockRepo.last_created.name == "Katie Reeves"
