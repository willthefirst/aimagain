"""Per-kind capability gates on post create.

`_assert_post_payload_authz` runs FK-ownership AND the matching
capability check from the two-claim verification model. Per handoff
§4.3 + §7, `referral` and `clinician_opening` require Claim A; a user
who owns the referenced Clinician but isn't `clinician_verified`
should be refused at the payload-authz boundary.

Two helpers handle this in `handlers.py`:

- The sync :func:`_assert_post_payload_capability` covers Claim A
  for `referral` / `clinician_opening` — pure predicates on the user
  object, no DB.
- The async :func:`_assert_program_intake_org_rep` covers Claim B
  for `program_intake` — requires loading the target Program's org.

The existing `_assert_post_payload_target_ownership` invariant (own
the FK target row) is exercised in higher-level integration tests;
these tests focus narrowly on the capability layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.logic.posts.handlers import (
    _assert_post_payload_capability,
    _assert_program_intake_org_rep,
)
from src.domain.models import Organization, Program
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


def test_program_intake_skipped_by_sync_claim_a_helper():
    """The sync `_assert_post_payload_capability` is the Claim-A gate
    only. `program_intake` payloads pass through it untouched — their
    Claim-B gate lives in the async `_assert_program_intake_org_rep`
    helper, called from the orchestrator immediately after."""
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


# ---------- _assert_program_intake_org_rep (async, Claim-B gate) ---------
#
# Stubbed-repo tests for the per-row Claim-B check. The orchestrator
# is exercised end-to-end in `test_org_rep_authority.py`; these tests
# pin the new helper's matrix narrowly.


class _Repo:
    """`get_by_model_id` stub that dispatches on the model class to a
    per-type lookup dict — same shape as the orchestrator-test repo
    in `test_org_rep_authority.py`."""

    def __init__(self, by_model: dict | None = None):
        self._by_model = by_model or {}
        self.calls: list = []

    async def get_by_model_id(self, model, model_id):
        self.calls.append((model.__name__, model_id))
        return self._by_model.get(model.__name__, {}).get(model_id)


def _intake_user(
    *,
    verified_rep_org_id=None,
    is_superuser: bool = False,
    is_verified: bool = True,
) -> SimpleNamespace:
    reps = (
        [
            SimpleNamespace(
                org_id=verified_rep_org_id,
                authority_status="verified",
                archived_at=None,
            )
        ]
        if verified_rep_org_id is not None
        else []
    )
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=is_superuser,
        is_verified=is_verified,
        org_representations=reps,
        clinicians=[],
    )


def _intake_payload(*, program_id) -> SimpleNamespace:
    return SimpleNamespace(kind="program_intake", program_id=program_id)


def _program_under(*, program_id, org_id) -> SimpleNamespace:
    return SimpleNamespace(id=program_id, org_id=org_id)


def _verified_org(*, org_id) -> SimpleNamespace:
    return SimpleNamespace(id=org_id, org_verified=True)


async def test_program_intake_org_rep_blocks_unverified_rep():
    """The user owns the referenced Program but isn't a verified rep
    of its org — the new helper 403s. This is the gap PR #1341 left
    open (picker-locked, server-open)."""
    program_id, org_id = uuid4(), uuid4()
    program_repo = _Repo(
        {
            Program.__name__: {
                program_id: _program_under(
                    program_id=program_id,
                    org_id=org_id,
                )
            }
        }
    )
    organization_repo = _Repo(
        {Organization.__name__: {org_id: _verified_org(org_id=org_id)}}
    )
    user = _intake_user(verified_rep_org_id=None)  # no Claim B

    with pytest.raises(ForbiddenError, match="Claim B"):
        await _assert_program_intake_org_rep(
            payload=_intake_payload(program_id=program_id),
            requesting_user=user,
            program_repo=program_repo,
            organization_repo=organization_repo,
        )


async def test_program_intake_org_rep_allows_verified_rep():
    """The user holds Claim B for the program's org — the helper
    returns cleanly (no exception). Paired with the previous test
    this pins the gate's positive truth value."""
    program_id, org_id = uuid4(), uuid4()
    program_repo = _Repo(
        {
            Program.__name__: {
                program_id: _program_under(
                    program_id=program_id,
                    org_id=org_id,
                )
            }
        }
    )
    organization_repo = _Repo(
        {Organization.__name__: {org_id: _verified_org(org_id=org_id)}}
    )
    user = _intake_user(verified_rep_org_id=org_id)

    await _assert_program_intake_org_rep(
        payload=_intake_payload(program_id=program_id),
        requesting_user=user,
        program_repo=program_repo,
        organization_repo=organization_repo,
    )


async def test_program_intake_org_rep_blocks_rep_for_wrong_org():
    """The user is a verified rep — but of a *different* org than the
    program's owning org. The per-row check uses the *program's* org,
    not the user's set of verified orgs, so this is rejected."""
    program_id, target_org_id, other_org_id = uuid4(), uuid4(), uuid4()
    program_repo = _Repo(
        {
            Program.__name__: {
                program_id: _program_under(
                    program_id=program_id,
                    org_id=target_org_id,
                )
            }
        }
    )
    organization_repo = _Repo(
        {Organization.__name__: {target_org_id: _verified_org(org_id=target_org_id)}}
    )
    # Rep for a different org — won't match the program's owning org.
    user = _intake_user(verified_rep_org_id=other_org_id)

    with pytest.raises(ForbiddenError, match="Claim B"):
        await _assert_program_intake_org_rep(
            payload=_intake_payload(program_id=program_id),
            requesting_user=user,
            program_repo=program_repo,
            organization_repo=organization_repo,
        )


async def test_program_intake_org_rep_skips_non_program_intake_payloads():
    """Referral/opening payloads hit the orchestrator with the same
    repos plumbed — the helper must no-op so it doesn't accidentally
    block other kinds."""
    referral_payload = SimpleNamespace(kind="referral", program_id=None)
    await _assert_program_intake_org_rep(
        payload=referral_payload,
        requesting_user=_intake_user(),
        program_repo=_Repo(),
        organization_repo=_Repo(),
    )


async def test_program_intake_org_rep_skips_when_program_id_missing():
    """PATCH-style payloads that don't touch the FK pass through — same
    discipline as the existing FK-ownership helper."""
    await _assert_program_intake_org_rep(
        payload=_intake_payload(program_id=None),
        requesting_user=_intake_user(),
        program_repo=_Repo(),
        organization_repo=_Repo(),
    )


async def test_program_intake_org_rep_skips_when_program_not_found():
    """If the Program doesn't load, the upstream ownership helper has
    already 404'd — re-checking here would only mask that error."""
    missing_id = uuid4()
    await _assert_program_intake_org_rep(
        payload=_intake_payload(program_id=missing_id),
        requesting_user=_intake_user(),
        program_repo=_Repo({Program.__name__: {}}),
        organization_repo=_Repo(),
    )


async def test_program_intake_org_rep_bypasses_for_superuser():
    """Admins write any row — same discipline as every other gate in
    this hook."""
    program_id, org_id = uuid4(), uuid4()
    # Repos return None for everything — would otherwise 403, but admin
    # bypass short-circuits before any load runs.
    program_repo = _Repo()
    organization_repo = _Repo()
    user = _intake_user(is_superuser=True)

    await _assert_program_intake_org_rep(
        payload=_intake_payload(program_id=program_id),
        requesting_user=user,
        program_repo=program_repo,
        organization_repo=organization_repo,
    )
    # Bypass means no DB load was issued.
    assert program_repo.calls == []
    assert organization_repo.calls == []


async def test_program_intake_org_rep_blocks_when_org_missing():
    """Program loads but its org doesn't — defensive 403 (shouldn't
    happen in practice given the FK constraint, but better than a
    silent allow if the row ever desyncs)."""
    program_id, org_id = uuid4(), uuid4()
    program_repo = _Repo(
        {
            Program.__name__: {
                program_id: _program_under(
                    program_id=program_id,
                    org_id=org_id,
                )
            }
        }
    )
    organization_repo = _Repo({Organization.__name__: {}})
    user = _intake_user(verified_rep_org_id=org_id)

    with pytest.raises(ForbiddenError, match="Claim B"):
        await _assert_program_intake_org_rep(
            payload=_intake_payload(program_id=program_id),
            requesting_user=user,
            program_repo=program_repo,
            organization_repo=organization_repo,
        )
