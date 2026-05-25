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

# Bespoke members not modeled by any spec.
#
# - `REGISTER` is fired by the fastapi-users self-signup flow in
#   `src/logic/auth/auth_processing.py` — there is no `RegistrationEntity`
#   spec, the verb just sits on top of `User`.
# - `JOB_RUN_STARTED` is fired by APScheduler-driven background jobs in
#   `src/jobs/` (system actor; `resource_type="job"`; per-run `resource_id`).
#   There is no spec home: a "job ran" event has no `AuditedResource` shape.
# - `CREATE_VERIFICATION` / `UPDATE_VERIFICATION` / `DELETE_VERIFICATION`
#   back the `AuditedResource` declared in
#   `src/domain/logic/verifications/handlers.py` (#528 / A4). Verification
#   has no public CRUD surface — the orchestrator writes append-only rows
#   from a bespoke trigger endpoint — so there is no EntitySpec for the
#   drift checker to derive these from. `make_audited_resource("verification", ...)`
#   still requires the full CREATE/UPDATE/DELETE triple as a precondition,
#   which is why UPDATE and DELETE are listed even though only CREATE is
#   wired to a callsite today.
#
# Keep tight: add an entry only when adding a corresponding
# `record_audit(action=...)` callsite or `AuditedResource` declaration.
_BESPOKE: frozenset[str] = frozenset(
    {
        "REGISTER",
        "JOB_RUN_STARTED",
        "CREATE_VERIFICATION",
        "UPDATE_VERIFICATION",
        "DELETE_VERIFICATION",
        # `UPDATE_USER_ONBOARDING_INTENT` is fired by
        # `PUT /users/me/onboarding-intent` (field-cluster subresource,
        # self-only). It has its own dedicated audit action rather than
        # reusing `UPDATE_USER` because `onboarding_intent` has separate
        # rules and its own before/after snapshot shape
        # (`OnboardingIntentAuditSnapshot`). There is no EntitySpec
        # subresource declaration for it — the route is a plain FastAPI
        # handler added directly to the users router.
        "UPDATE_USER_ONBOARDING_INTENT",
    }
)


def _expected_members() -> set[str]:
    expected: set[str] = set(_BESPOKE)
    for spec in ALL_ENTITY_SPECS:
        if spec.audit is not None:
            # The stem for the *enum member name* comes off the
            # AuditedResource's own create/update/delete action names,
            # not from `spec.name` directly — kind-locked faces of a
            # polymorphic supertype (`discriminator_value` set) share
            # one AuditedResource whose stem is the supertype name
            # ("post"), not the face name ("referral" etc.). Reading
            # through `spec.audit` keeps the test correct for both
            # shapes without a special case.
            expected.add(spec.audit.create.name)
            expected.add(spec.audit.update.name)
            expected.add(spec.audit.delete.name)
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
