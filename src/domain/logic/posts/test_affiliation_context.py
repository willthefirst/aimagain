"""Unit tests for `_resolve_affiliation_context` — the picker-derives-
clinician step that runs before FK-ownership on post create/update.

The opening / referral forms submit a single `clinician_affiliation_id`
(the practice picker). The server derives the listing's clinician FK
from that affiliation's `clinician_id`:

  - `kind='referral'`          → `referring_clinician_id`
  - `kind='clinician_opening'` → `clinician_id`

The derived value is set on the payload in place so it flows through
both `model_dump()` (create) and `model_dump(exclude_unset=True)`
(update). These tests pin the per-kind target, the missing-affiliation
404, and the no-op when no `clinician_affiliation_id` is present.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domain.logic.posts.handlers import _resolve_affiliation_context
from src.framework.http.exceptions import NotFoundError


class _StubClinicianRepo:
    """Returns `affiliation` for any `get_by_model_id` call, or None to
    simulate a missing row."""

    def __init__(self, affiliation):
        self._affiliation = affiliation
        self.calls: list = []

    async def get_by_model_id(self, model, model_id):
        self.calls.append((model, model_id))
        return self._affiliation


async def test_referral_derives_referring_clinician_id():
    clinician_id = uuid4()
    aff_id = uuid4()
    affiliation = SimpleNamespace(id=aff_id, clinician_id=clinician_id)
    payload = SimpleNamespace(
        kind="referral",
        clinician_affiliation_id=aff_id,
        referring_clinician_id=None,
    )
    repo = _StubClinicianRepo(affiliation)

    await _resolve_affiliation_context(payload=payload, clinician_repo=repo)

    assert payload.referring_clinician_id == clinician_id


async def test_opening_derives_clinician_id():
    clinician_id = uuid4()
    aff_id = uuid4()
    affiliation = SimpleNamespace(id=aff_id, clinician_id=clinician_id)
    payload = SimpleNamespace(
        kind="clinician_opening",
        clinician_affiliation_id=aff_id,
        clinician_id=None,
    )
    repo = _StubClinicianRepo(affiliation)

    await _resolve_affiliation_context(payload=payload, clinician_repo=repo)

    assert payload.clinician_id == clinician_id


async def test_missing_affiliation_raises_not_found():
    aff_id = uuid4()
    payload = SimpleNamespace(
        kind="referral",
        clinician_affiliation_id=aff_id,
        referring_clinician_id=None,
    )
    repo = _StubClinicianRepo(None)

    with pytest.raises(NotFoundError, match=str(aff_id)):
        await _resolve_affiliation_context(payload=payload, clinician_repo=repo)


async def test_no_affiliation_id_is_noop():
    """A `program_intake` payload (no picker) or a PATCH that doesn't
    touch context carries no `clinician_affiliation_id` — the repo is
    never hit and nothing is derived."""
    payload = SimpleNamespace(kind="program_intake", program_id=uuid4())
    repo = _StubClinicianRepo(SimpleNamespace(clinician_id=uuid4()))

    await _resolve_affiliation_context(payload=payload, clinician_repo=repo)

    assert repo.calls == []


async def test_none_affiliation_id_is_noop():
    """An opening/referral PATCH that leaves the picker untouched has
    `clinician_affiliation_id=None` — also a no-op, no derivation."""
    payload = SimpleNamespace(
        kind="referral",
        clinician_affiliation_id=None,
        referring_clinician_id=None,
    )
    repo = _StubClinicianRepo(SimpleNamespace(clinician_id=uuid4()))

    await _resolve_affiliation_context(payload=payload, clinician_repo=repo)

    assert repo.calls == []
    assert payload.referring_clinician_id is None
