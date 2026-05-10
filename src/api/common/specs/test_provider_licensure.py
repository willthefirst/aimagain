"""Spec-correctness suite for `LICENSURE_ENTITY`."""

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction
from src.models import ProviderLicensure
from src.schemas.providers.provider import (
    licensure_create_adapter,
    licensure_update_adapter,
)


def test_identity_fields():
    assert LICENSURE_ENTITY.name == "provider_licensure"
    assert LICENSURE_ENTITY.url_collection == "licensures"
    assert LICENSURE_ENTITY.id_param == "licensure_id"
    assert LICENSURE_ENTITY.model is ProviderLicensure


def test_parent_is_provider_entity():
    assert LICENSURE_ENTITY.parent is PROVIDER_ENTITY


def test_audit_binding():
    assert LICENSURE_ENTITY.audit is not None
    assert LICENSURE_ENTITY.audit.type == "provider_licensure"
    assert LICENSURE_ENTITY.audit.create == AuditAction.CREATE_LICENSURE
    assert LICENSURE_ENTITY.audit.update == AuditAction.UPDATE_LICENSURE
    assert LICENSURE_ENTITY.audit.delete == AuditAction.DELETE_LICENSURE


def test_routes_opted_in():
    """Subrow CRUD only — no independent list/detail/form pages."""
    assert LICENSURE_ENTITY.routes == RouteSet(create=True, update=True, delete=True)


def test_adapters_are_the_canonical_ones():
    assert LICENSURE_ENTITY.create_adapter is licensure_create_adapter
    assert LICENSURE_ENTITY.update_adapter is licensure_update_adapter


def test_write_authz_is_assert_owner_or_admin():
    assert LICENSURE_ENTITY.write_authz is assert_owner_or_admin


def test_redirects_target_parent_form():
    """Sub-row mutations send HTMX clients back to the parent edit form."""
    target = "/providers/abc-123/form"
    assert LICENSURE_ENTITY.create_redirect(provider_id="abc-123") == target
    assert LICENSURE_ENTITY.update_redirect(provider_id="abc-123") == target
    assert LICENSURE_ENTITY.delete_redirect(provider_id="abc-123") == target


def test_to_resource_spec_walks_parent_chain():
    rs = LICENSURE_ENTITY.to_resource_spec()
    assert rs.collection == "licensures"
    assert rs.parent is not None
    assert rs.parent.collection == "providers"
    assert rs.parent.id_param == "provider_id"
