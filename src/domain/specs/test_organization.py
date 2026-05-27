"""Entity-specific facts for `ORGANIZATION_ENTITY`.

Universal invariants live in `test_spec_conformance.py`; this file pins
what's unique to the organization spec — routes opted in, post-mutation
redirects, the auth-policy expansion, and the static-context wiring.
"""

from src.domain.logic.organizations.schema import (
    OrganizationRead,
)
from src.domain.models import Organization
from src.domain.specs.organization import ORGANIZATION_ENTITY
from src.framework.dispatch.entity_spec import AUTHENTICATED, OWNER_OR_ADMIN


def test_identity_pins_url_and_param():
    assert ORGANIZATION_ENTITY.name == "organization"
    assert ORGANIZATION_ENTITY.url_collection == "organizations"
    assert ORGANIZATION_ENTITY.id_param == "organization_id"
    assert ORGANIZATION_ENTITY.model is Organization


def test_routes_opt_in_full_crud():
    routes = ORGANIZATION_ENTITY.routes
    assert routes.list
    assert routes.detail
    assert routes.create
    assert routes.update
    assert routes.delete
    assert routes.form_new
    assert routes.form_edit


def test_auth_deps_is_authenticated():
    assert ORGANIZATION_ENTITY.auth_deps is AUTHENTICATED


def test_auth_policy_is_owner_or_admin():
    assert ORGANIZATION_ENTITY.auth_policy is OWNER_OR_ADMIN


def test_create_and_update_redirect_to_edit_form():
    target = "/organizations/abc-123/form"
    assert ORGANIZATION_ENTITY.create_redirect(organization_id="abc-123") == target
    assert ORGANIZATION_ENTITY.update_redirect(organization_id="abc-123") == target


def test_delete_redirect_unset():
    """Delete falls back to the mount layer's default of `/organizations`."""
    assert ORGANIZATION_ENTITY.delete_redirect is None


def test_schemas_wired_correctly():
    # `EntitySpec.__post_init__` wraps these in `TypeAdapter`; check the
    # underlying class via `.core_schema` instead of identity.
    from pydantic import TypeAdapter

    assert isinstance(ORGANIZATION_ENTITY.create_adapter, TypeAdapter)
    assert isinstance(ORGANIZATION_ENTITY.update_adapter, TypeAdapter)
    assert ORGANIZATION_ENTITY.read_schema is OrganizationRead


def test_form_extras_path_drives_parent_org_picker():
    """Issue #581: the parent-Org picker is populated via the framework's
    ``form_extras_path`` hook — same shape as Clinician/Program."""
    assert (
        ORGANIZATION_ENTITY.form_extras_path
        == "src.domain.logic.organizations.handlers.organization_form_extras"
    )
    from src.domain.logic.organizations.repository import OrganizationRepository

    assert ORGANIZATION_ENTITY.form_extras_repos == (
        ("organization_repo", OrganizationRepository),
    )


def test_static_context_carries_type_vocabulary():
    from src.domain.models.enums import (
        ORGANIZATION_TYPES,
        ORGANIZATION_TYPES_LABELS,
    )

    assert ORGANIZATION_ENTITY.static_context == {
        "ORGANIZATION_TYPES": ORGANIZATION_TYPES,
        "ORGANIZATION_TYPES_LABELS": ORGANIZATION_TYPES_LABELS,
    }
