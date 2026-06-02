"""Org-rep authority path on post create (`_assert_post_payload_authz`).

PR 3c wires the **org-rep (Claim B) authority chain**: a user who is a
verified `OrgRepresentation` for an org may create a referral/opening
whose `clinician_affiliation_id` points at a clinician affiliated with
that org — without owning the clinician or holding Claim A. The
affiliation *is* the clinician↔org link, so the org rep's authority
flows `OrgRepresentation → org → affiliation → clinician`.

These tests pin the create-path orchestrator end-to-end with stubbed
repos: the rep path authorizes (early return, no ownership/Claim-A
check), and every miss in the chain falls through to the existing
self/owner authority path. Edit-by-non-owner-rep is *not* covered —
that path is gated by the object-level `write_authz` (owner-or-admin)
that runs before this hook on PATCH, and is a separate change.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.logic.posts.handlers import (
    _assert_post_payload_authz,
    _is_verified_org_rep_for_affiliation,
)
from src.domain.models import Clinician, ClinicianAffiliation, Organization
from src.framework.http.exceptions import ForbiddenError


class _Repo:
    """`get_by_model_id` stub that dispatches on the requested model
    class to a per-type lookup dict, mirroring the real repos closely
    enough for the authz orchestrator."""

    def __init__(self, by_model: dict):
        self._by_model = by_model
        self.calls: list = []

    async def get_by_model_id(self, model, model_id):
        self.calls.append((model.__name__, model_id))
        return self._by_model.get(model.__name__, {}).get(model_id)


def _user(
    *,
    user_id=None,
    is_superuser=False,
    verified_rep_org_id=None,
    clinician_verified=False,
):
    user_id = user_id or uuid4()
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
    clinicians = (
        [SimpleNamespace(clinician_verified=True)] if clinician_verified else []
    )
    return SimpleNamespace(
        id=user_id,
        is_superuser=is_superuser,
        is_verified=True,
        org_representations=reps,
        clinicians=clinicians,
    )


def _referral_payload(*, aff_id):
    return SimpleNamespace(
        kind="referral",
        clinician_affiliation_id=aff_id,
        referring_clinician_id=None,
    )


def _opening_payload(*, aff_id):
    return SimpleNamespace(
        kind="clinician_opening",
        clinician_affiliation_id=aff_id,
        clinician_id=None,
    )


def _setup(*, owner_id, org_verified=True):
    """Build coherent affiliation/clinician/org rows: an affiliation of
    `clinician` (owned by `owner_id`) at `org`. Returns ids + repos."""
    aff_id, clin_id, org_id = uuid4(), uuid4(), uuid4()
    affiliation = SimpleNamespace(id=aff_id, clinician_id=clin_id, org_id=org_id)
    clinician = SimpleNamespace(id=clin_id, owner_id=owner_id)
    org = SimpleNamespace(id=org_id, org_verified=org_verified)
    clinician_repo = _Repo(
        {
            ClinicianAffiliation.__name__: {aff_id: affiliation},
            Clinician.__name__: {clin_id: clinician},
        }
    )
    organization_repo = _Repo({Organization.__name__: {org_id: org}})
    return SimpleNamespace(
        aff_id=aff_id,
        clin_id=clin_id,
        org_id=org_id,
        clinician_repo=clinician_repo,
        organization_repo=organization_repo,
    )


async def _run(payload, user, fx):
    await _assert_post_payload_authz(
        payload=payload,
        requesting_user=user,
        clinician_repo=fx.clinician_repo,
        program_repo=_Repo({}),
        organization_repo=fx.organization_repo,
    )


async def test_org_rep_authorizes_referral_without_owning_clinician():
    """A verified rep of the affiliation's org may post a referral under
    that affiliation's clinician even though someone else owns the
    clinician and the rep holds no Claim A."""
    fx = _setup(owner_id=uuid4())  # clinician owned by a *different* user
    rep = _user(verified_rep_org_id=fx.org_id, clinician_verified=False)

    await _run(_referral_payload(aff_id=fx.aff_id), rep, fx)

    # Early return on the rep path: the ownership check (which would load
    # the Clinician and 403) never ran.
    assert (Clinician.__name__, fx.clin_id) not in fx.clinician_repo.calls


async def test_org_rep_authorizes_opening():
    fx = _setup(owner_id=uuid4())
    rep = _user(verified_rep_org_id=fx.org_id)

    await _run(_opening_payload(aff_id=fx.aff_id), rep, fx)

    assert (Clinician.__name__, fx.clin_id) not in fx.clinician_repo.calls


async def test_unverified_org_falls_through_to_self_path_and_403s():
    """If the org's Type-2 NPI isn't verified, `org_rep_verified` is
    False — the rep path is skipped and the non-owner is rejected by the
    self/ownership path."""
    fx = _setup(owner_id=uuid4(), org_verified=False)
    rep = _user(verified_rep_org_id=fx.org_id)

    with pytest.raises(ForbiddenError):
        await _run(_referral_payload(aff_id=fx.aff_id), rep, fx)


async def test_non_rep_non_owner_is_rejected():
    """A user who is neither a rep of the org nor the clinician's owner
    falls through to the self path and is rejected."""
    fx = _setup(owner_id=uuid4())
    stranger = _user()  # no rep, owns nothing

    with pytest.raises(ForbiddenError):
        await _run(_referral_payload(aff_id=fx.aff_id), stranger, fx)


async def test_owner_with_claim_a_takes_self_path():
    """The owner path still works: owning the clinician + Claim A
    authorizes even with no org-rep status."""
    owner_id = uuid4()
    fx = _setup(owner_id=owner_id)
    owner = _user(user_id=owner_id, clinician_verified=True)

    await _run(_referral_payload(aff_id=fx.aff_id), owner, fx)


async def test_superuser_falls_through_and_is_authorized():
    """A superuser who isn't a rep falls through to the self path, where
    ownership + capability both bypass for admins."""
    fx = _setup(owner_id=uuid4())
    admin = _user(is_superuser=True)

    await _run(_referral_payload(aff_id=fx.aff_id), admin, fx)


async def test_is_verified_org_rep_false_when_org_missing():
    aff = SimpleNamespace(org_id=uuid4(), clinician_id=uuid4())
    organization_repo = _Repo({})  # org not found
    result = await _is_verified_org_rep_for_affiliation(
        affiliation=aff,
        requesting_user=_user(verified_rep_org_id=aff.org_id),
        organization_repo=organization_repo,
    )
    assert result is False
