"""Entity-specific facts for `ORG_REPRESENTATION_ENTITY`.

Universal invariants live in `test_spec_conformance.py`. This file pins
the org-rep-specific bits: owner_attr points at `user_id` (not the
default `owner_id`), routes opt into CRUD-without-list/detail, and the
`authority` state-axis is wired with `forbid_self=False` (the approver
of a rep_approval is normally NOT the same person — but an admin
verifying their own first-claim is still legitimate).
"""

from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import AUTHENTICATED, OWNER_OR_ADMIN


def test_owner_attr_is_user_id():
    """The resource is User-owned (the row represents a user); authz
    reads `OrgRepresentation.user_id` — not the default `owner_id`."""
    assert ORG_REPRESENTATION_ENTITY.owner_attr == "user_id"


def test_auth_deps_authenticated_and_policy_owner_or_admin():
    assert ORG_REPRESENTATION_ENTITY.auth_deps is AUTHENTICATED
    assert ORG_REPRESENTATION_ENTITY.auth_policy is OWNER_OR_ADMIN


def test_routes_update_delete_only_no_collection_views():
    """API-only routes. `create=False` because the bespoke handler
    `handle_create_org_representation` (with per-authority-method
    dispatch) owns POST `/org_representations`; the framework's
    generic create would land every row at `authority_status='pending'`
    and miss the `authorized_official` auto-verify happy path."""
    r = ORG_REPRESENTATION_ENTITY.routes
    assert r.create is False
    assert (r.update, r.delete) == (True, True)
    assert (r.list, r.detail, r.form_new, r.form_edit) == (False, False, False, False)


def test_authority_state_axis_wired():
    axis = ORG_REPRESENTATION_ENTITY.state_axis("authority")
    assert axis.action is AuditAction.SET_ORG_REPRESENTATION_AUTHORITY
    assert axis.handler_path == (
        "src.domain.logic.org_representations.handlers."
        "handle_set_org_representation_authority"
    )
    # `forbid_self` is False — an admin should be able to verify their
    # own first-claim representation (e.g. the solo practitioner whose
    # NPPES Authorized-Official name matched). Self-vs-other authz
    # lives in the handler, not the axis flag.
    assert axis.forbid_self is False


def test_audit_resource_type_matches_name():
    assert ORG_REPRESENTATION_ENTITY.audit is not None
    assert ORG_REPRESENTATION_ENTITY.audit.type == "org_representation"
    assert (
        ORG_REPRESENTATION_ENTITY.audit.create is AuditAction.CREATE_ORG_REPRESENTATION
    )
    assert (
        ORG_REPRESENTATION_ENTITY.audit.update is AuditAction.UPDATE_ORG_REPRESENTATION
    )
    assert (
        ORG_REPRESENTATION_ENTITY.audit.delete is AuditAction.DELETE_ORG_REPRESENTATION
    )
