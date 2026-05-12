"""Drift guard: every `AuditAction` member is justified by a spec.

`AuditAction` values are persisted forever, so the enum stays
hand-typed (we don't generate it). But every member should be either:

  - Derived from a CRUD spec's `audit_action_stem` (or its `name`
    when the stem isn't overridden) → `CREATE_<STEM>` /
    `UPDATE_<STEM>` / `DELETE_<STEM>`.
  - Declared on an edge spec's `edge_audit.actions`.
  - Declared on a CRUD spec's `state_axes[i].action`.
  - Justified by the auth bespoke allow-list (`REGISTER`).

`make_audited_resource` already raises at import time when a spec
references a missing member (forward direction). This test enforces
the reverse: an enum member with no spec home is dead weight and a
sign of stale code.
"""

from src.domain.specs.post import POST_ENTITY
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.domain.specs.user import USER_ENTITY
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework.audit import AuditAction

# All CRUD-shaped specs whose `audit` binding should account for a
# `CREATE_<STEM>`/`UPDATE_<STEM>`/`DELETE_<STEM>` triple.
_CRUD_SPECS = (
    USER_ENTITY,
    POST_ENTITY,
    PROVIDER_ENTITY,
    LICENSURE_ENTITY,
    EDUCATION_ENTITY,
    CERTIFICATION_ENTITY,
)

# Edge-shaped specs whose `edge_audit.actions` declares each member directly.
_EDGE_SPECS = (FAVORITE_ENTITY,)

# Specs whose state axes declare standalone audit actions outside the
# CRUD triple. Each `state_axes[i].action` is its own enum member.
_STATE_AXIS_SPECS = (USER_ENTITY,)

# Bespoke members not modeled by any spec. `REGISTER` is fired by the
# fastapi-users self-signup flow in `src/logic/auth/auth_processing.py`
# — there is no `RegistrationEntity` spec, the verb just sits on top of
# `User`. Keep tight: add an entry only when adding a corresponding
# `record_audit(action=...)` callsite.
_BESPOKE: frozenset[str] = frozenset({"REGISTER"})


def _expected_members() -> set[str]:
    expected: set[str] = set(_BESPOKE)
    for spec in _CRUD_SPECS:
        stem = (spec.audit_action_stem or spec.name).upper()
        expected.update({f"CREATE_{stem}", f"UPDATE_{stem}", f"DELETE_{stem}"})
    for spec in _EDGE_SPECS:
        for action in spec.edge_audit.actions.values():
            expected.add(action.name)
    for spec in _STATE_AXIS_SPECS:
        for axis in spec.state_axes:
            expected.add(axis.action.name)
    return expected


def test_audit_action_members_match_specs():
    """Every `AuditAction` member must be justified by a spec (CRUD
    triple, edge action, state-axis action) or the bespoke allow-list.

    Adding a spec → import-time `make_audited_resource` will require
    the matching members. Removing a spec → this test fails until the
    orphaned members are removed from the enum. Values are persisted
    forever, so dropping an enum value is a deliberate migration step.
    """
    declared = {member.name for member in AuditAction}
    expected = _expected_members()

    missing = expected - declared
    extra = declared - expected

    assert not missing, (
        f"AuditAction is missing members referenced by specs: "
        f"{sorted(missing)}. Add them to AuditAction or fix the spec."
    )
    assert not extra, (
        f"AuditAction has orphaned members with no spec home: "
        f"{sorted(extra)}. Either add a spec that uses them, list "
        f"them in _BESPOKE, or remove them from the enum (after "
        f"confirming no persisted audit rows still reference the value)."
    )
