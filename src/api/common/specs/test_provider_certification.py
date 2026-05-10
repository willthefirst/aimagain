"""Spec-correctness suite for `CERTIFICATION_ENTITY`."""

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction
from src.models import ProviderCertification
from src.schemas.providers.provider import (
    certification_create_adapter,
    certification_update_adapter,
)


def test_identity_fields():
    assert CERTIFICATION_ENTITY.name == "provider_certification"
    assert CERTIFICATION_ENTITY.url_collection == "certifications"
    assert CERTIFICATION_ENTITY.id_param == "certification_id"
    assert CERTIFICATION_ENTITY.model is ProviderCertification


def test_parent_is_provider_entity():
    assert CERTIFICATION_ENTITY.parent is PROVIDER_ENTITY


def test_audit_binding():
    assert CERTIFICATION_ENTITY.audit is not None
    assert CERTIFICATION_ENTITY.audit.type == "provider_certification"
    assert CERTIFICATION_ENTITY.audit.create == AuditAction.CREATE_CERTIFICATION
    assert CERTIFICATION_ENTITY.audit.update == AuditAction.UPDATE_CERTIFICATION
    assert CERTIFICATION_ENTITY.audit.delete == AuditAction.DELETE_CERTIFICATION


def test_routes_opted_in():
    assert CERTIFICATION_ENTITY.routes == RouteSet(
        create=True, update=True, delete=True
    )


def test_adapters_are_the_canonical_ones():
    assert CERTIFICATION_ENTITY.create_adapter is certification_create_adapter
    assert CERTIFICATION_ENTITY.update_adapter is certification_update_adapter


def test_write_authz_is_assert_owner_or_admin():
    assert CERTIFICATION_ENTITY.write_authz is assert_owner_or_admin


def test_redirects_target_parent_form():
    target = "/providers/abc-123/form"
    assert CERTIFICATION_ENTITY.create_redirect(provider_id="abc-123") == target
    assert CERTIFICATION_ENTITY.update_redirect(provider_id="abc-123") == target
    assert CERTIFICATION_ENTITY.delete_redirect(provider_id="abc-123") == target


def test_to_resource_spec_walks_parent_chain():
    rs = CERTIFICATION_ENTITY.to_resource_spec()
    assert rs.collection == "certifications"
    assert rs.parent is not None
    assert rs.parent.collection == "providers"
