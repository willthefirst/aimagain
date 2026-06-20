"""Entity-specific facts for `SAVED_SEARCH_ENTITY`.

Universal invariants live in `test_spec_conformance.py`. This file pins
the saved-search-specific bits: it's a `parent=USER_ENTITY` owned
subentity (the first one), authz is self-or-admin (not owner-or-admin,
because the parent *is* the user), and it opts into the full CRUD +
form route set.
"""

from src.domain.specs.saved_search import SAVED_SEARCH_ENTITY
from src.domain.specs.user import USER_ENTITY
from src.framework.access.authz.authz import assert_self_or_admin
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import AUTHENTICATED


def test_parent_is_user_entity():
    assert SAVED_SEARCH_ENTITY.parent is USER_ENTITY
    # Registered as an owned subentity so `mount_entity(USER_ENTITY)`
    # picks it up via `USER_ENTITY.children`.
    assert SAVED_SEARCH_ENTITY in USER_ENTITY.children


def test_default_parent_fk_convention():
    """No FK override — the child holds `user_id` (= `<parent.name>_id`),
    which is exactly our owner column."""
    assert SAVED_SEARCH_ENTITY.parent_fk_attr is None
    assert SAVED_SEARCH_ENTITY.child_parent_match_attr is None


def test_auth_is_self_or_admin_not_owner_or_admin():
    """The parent is the user itself (no `owner_id`), so write_authz is
    `assert_self_or_admin`, hand-wired rather than via OWNER_OR_ADMIN."""
    assert SAVED_SEARCH_ENTITY.auth_deps is AUTHENTICATED
    assert SAVED_SEARCH_ENTITY.write_authz is assert_self_or_admin
    assert SAVED_SEARCH_ENTITY.auth_policy is None


def test_routes_full_crud_with_forms_no_detail():
    r = SAVED_SEARCH_ENTITY.routes
    assert (r.list, r.create, r.update, r.delete) == (True, True, True, True)
    assert (r.form_new, r.form_edit) == (True, True)
    # No standalone detail page — the edit form is the row's page.
    assert r.detail is False


def test_audit_resource_wired():
    assert SAVED_SEARCH_ENTITY.audit is not None
    assert SAVED_SEARCH_ENTITY.audit.type == "saved_search"
    assert SAVED_SEARCH_ENTITY.audit.create is AuditAction.CREATE_SAVED_SEARCH
    assert SAVED_SEARCH_ENTITY.audit.update is AuditAction.UPDATE_SAVED_SEARCH
    assert SAVED_SEARCH_ENTITY.audit.delete is AuditAction.DELETE_SAVED_SEARCH
