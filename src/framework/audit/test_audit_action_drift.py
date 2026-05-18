"""Drift guard: every `AuditAction` member is justified by a spec.

The CRUD / edge / state-axis partition is derived by iterating
:data:`src.domain.specs.ALL_ENTITY_SPECS` — no hand-listed tuple per
audit shape. Adding a new entity means adding it to that re-export
tuple and the matching ``CREATE_<STEM>`` / ``UPDATE_<STEM>`` /
``DELETE_<STEM>`` members to :class:`AuditAction`; this drift guard
flags any missing piece.
"""

from src.domain.specs import ALL_ENTITY_SPECS
from src.framework.audit.core import AuditAction

# Bespoke members not modeled by any spec. `REGISTER` is fired by the
# fastapi-users self-signup flow in `src/logic/auth/auth_processing.py`
# — there is no `RegistrationEntity` spec, the verb just sits on top of
# `User`. Keep tight: add an entry only when adding a corresponding
# `record_audit(action=...)` callsite.
_BESPOKE: frozenset[str] = frozenset({"REGISTER"})


def _expected_members() -> set[str]:
    expected: set[str] = set(_BESPOKE)
    for spec in ALL_ENTITY_SPECS:
        if spec.audit is not None:
            stem = (spec.audit_action_stem or spec.name).upper()
            expected.update({f"CREATE_{stem}", f"UPDATE_{stem}", f"DELETE_{stem}"})
        if spec.edge_audit is not None:
            for action in spec.edge_audit.actions.values():
                expected.add(action.name)
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
