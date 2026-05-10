"""Spec-correctness suite for `EDUCATION_ENTITY`."""

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction
from src.models import ProviderEducation
from src.schemas.providers.provider import (
    education_create_adapter,
    education_update_adapter,
)


def test_identity_fields():
    assert EDUCATION_ENTITY.name == "provider_education"
    assert EDUCATION_ENTITY.url_collection == "educations"
    assert EDUCATION_ENTITY.id_param == "education_id"
    assert EDUCATION_ENTITY.model is ProviderEducation


def test_parent_is_provider_entity():
    assert EDUCATION_ENTITY.parent is PROVIDER_ENTITY


def test_audit_binding():
    assert EDUCATION_ENTITY.audit is not None
    assert EDUCATION_ENTITY.audit.type == "provider_education"
    assert EDUCATION_ENTITY.audit.create == AuditAction.CREATE_EDUCATION
    assert EDUCATION_ENTITY.audit.update == AuditAction.UPDATE_EDUCATION
    assert EDUCATION_ENTITY.audit.delete == AuditAction.DELETE_EDUCATION


def test_routes_opted_in():
    assert EDUCATION_ENTITY.routes == RouteSet(create=True, update=True, delete=True)


def test_adapters_are_the_canonical_ones():
    assert EDUCATION_ENTITY.create_adapter is education_create_adapter
    assert EDUCATION_ENTITY.update_adapter is education_update_adapter


def test_write_authz_is_assert_owner_or_admin():
    assert EDUCATION_ENTITY.write_authz is assert_owner_or_admin


def test_redirects_target_parent_form():
    target = "/providers/abc-123/form"
    assert EDUCATION_ENTITY.create_redirect(provider_id="abc-123") == target
    assert EDUCATION_ENTITY.update_redirect(provider_id="abc-123") == target
    assert EDUCATION_ENTITY.delete_redirect(provider_id="abc-123") == target


def test_to_resource_spec_walks_parent_chain():
    rs = EDUCATION_ENTITY.to_resource_spec()
    assert rs.collection == "educations"
    assert rs.parent is not None
    assert rs.parent.collection == "providers"
