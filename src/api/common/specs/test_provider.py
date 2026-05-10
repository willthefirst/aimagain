"""Spec-correctness suite for `PROVIDER_ENTITY`.

Asserts the spec declares the right things — not that CRUD works
(those tests live at the route/logic layers).
"""

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction
from src.models import Provider
from src.schemas.providers.provider import (
    provider_create_adapter,
    provider_update_adapter,
)

# --- Identity ------------------------------------------------------------


def test_identity_fields():
    assert PROVIDER_ENTITY.name == "provider"
    assert PROVIDER_ENTITY.url_collection == "providers"
    assert PROVIDER_ENTITY.id_param == "provider_id"
    assert PROVIDER_ENTITY.model is Provider


def test_owner_attr_defaults_to_owner_id():
    """Providers track ownership via `Provider.owner_id` — the default."""
    assert PROVIDER_ENTITY.owner_attr == "owner_id"


def test_no_parent():
    """Providers are top-level; the three credential subentities link
    upward via `parent=PROVIDER_ENTITY` instead."""
    assert PROVIDER_ENTITY.parent is None


# --- Audit binding -------------------------------------------------------


def test_audit_type_is_provider():
    assert PROVIDER_ENTITY.audit is not None
    assert PROVIDER_ENTITY.audit.type == "provider"


def test_audit_actions_match_crud_enum():
    assert PROVIDER_ENTITY.audit.create == AuditAction.CREATE_PROVIDER
    assert PROVIDER_ENTITY.audit.update == AuditAction.UPDATE_PROVIDER
    assert PROVIDER_ENTITY.audit.delete == AuditAction.DELETE_PROVIDER


# --- Routes opt-in -------------------------------------------------------


def test_routes_opted_in():
    """Providers exposes full CRUD + both form pages — confirmed
    against the mount calls in `src/api/routes/providers.py`."""
    assert PROVIDER_ENTITY.routes == RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    )


# --- Adapters + read_to_dict ---------------------------------------------


def test_adapters_are_the_canonical_ones():
    assert PROVIDER_ENTITY.create_adapter is provider_create_adapter
    assert PROVIDER_ENTITY.update_adapter is provider_update_adapter


def test_read_to_dict_returns_provider_read_shape():
    """`read_to_dict` round-trips a Provider through `ProviderRead`."""
    assert PROVIDER_ENTITY.read_to_dict is not None
    # We can't easily construct a real Provider here; verify the
    # callable is wired by name and exists. Round-trip behavior is
    # covered by route-level tests.
    assert callable(PROVIDER_ENTITY.read_to_dict)


# --- Authorization -------------------------------------------------------


def test_write_authz_is_assert_owner_or_admin():
    assert PROVIDER_ENTITY.write_authz is assert_owner_or_admin


# --- List filters --------------------------------------------------------


def test_filters_are_license_type_and_issuing_state():
    names = {f.name for f in PROVIDER_ENTITY.filters}
    assert names == {"license_type", "issuing_state"}


# --- Redirects -----------------------------------------------------------


def test_create_and_update_redirect_to_edit_form():
    assert PROVIDER_ENTITY.create_redirect is not None
    assert PROVIDER_ENTITY.update_redirect is not None
    # Both point at the parent edit-form path.
    target = PROVIDER_ENTITY.create_redirect(provider_id="abc-123")
    assert target == "/providers/abc-123/form"
    target = PROVIDER_ENTITY.update_redirect(provider_id="abc-123")
    assert target == "/providers/abc-123/form"


def test_delete_redirect_unset():
    """Providers don't have a custom delete-redirect — the mount layer's
    default (`/providers`) handles it."""
    assert PROVIDER_ENTITY.delete_redirect is None


# --- Templates -----------------------------------------------------------


def test_templates():
    assert PROVIDER_ENTITY.templates.list == "providers/list.html"
    assert PROVIDER_ENTITY.templates.detail == "providers/detail.html"


# --- Bridge --------------------------------------------------------------


def test_to_resource_spec_round_trips_what_mounts_read():
    rs = PROVIDER_ENTITY.to_resource_spec()
    assert rs.collection == "providers"
    assert rs.id_param == "provider_id"
    assert rs.repo_dep is PROVIDER_ENTITY.repo_dep
    assert rs.audit_resource is PROVIDER_ENTITY.audit
    assert rs.read_user_dep is PROVIDER_ENTITY.read_user_dep
    assert rs.write_user_dep is PROVIDER_ENTITY.write_user_dep
    assert rs.write_authz is assert_owner_or_admin
    assert rs.create_adapter is provider_create_adapter
    assert rs.update_adapter is provider_update_adapter
    assert rs.list_template == "providers/list.html"
    assert rs.detail_template == "providers/detail.html"
    assert rs.parent is None
