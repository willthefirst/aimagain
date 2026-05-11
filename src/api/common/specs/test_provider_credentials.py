"""Spec-correctness suite for the three provider-credential subentities.

All three share the factory in `_credential.py`; the per-credential
test parameters are the only varying inputs (identity, model, audit
actions, schemas). The factory output is checked once per credential
via parametrization to keep coverage explicit without three near-identical
test modules.
"""

import pytest
from pydantic import TypeAdapter

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic._authz import assert_owner_or_admin, is_owner_or_admin
from src.logic.audit import AuditAction
from src.models import ProviderCertification, ProviderEducation, ProviderLicensure
from src.schemas.providers.provider import (
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
)

CREDENTIALS = [
    pytest.param(
        LICENSURE_ENTITY,
        "provider_licensure",
        "licensures",
        "licensure_id",
        ProviderLicensure,
        (
            AuditAction.CREATE_LICENSURE,
            AuditAction.UPDATE_LICENSURE,
            AuditAction.DELETE_LICENSURE,
        ),
        ProviderLicensureCreate,
        ProviderLicensureUpdate,
        id="licensure",
    ),
    pytest.param(
        EDUCATION_ENTITY,
        "provider_education",
        "educations",
        "education_id",
        ProviderEducation,
        (
            AuditAction.CREATE_EDUCATION,
            AuditAction.UPDATE_EDUCATION,
            AuditAction.DELETE_EDUCATION,
        ),
        ProviderEducationCreate,
        ProviderEducationUpdate,
        id="education",
    ),
    pytest.param(
        CERTIFICATION_ENTITY,
        "provider_certification",
        "certifications",
        "certification_id",
        ProviderCertification,
        (
            AuditAction.CREATE_CERTIFICATION,
            AuditAction.UPDATE_CERTIFICATION,
            AuditAction.DELETE_CERTIFICATION,
        ),
        ProviderCertificationCreate,
        ProviderCertificationUpdate,
        id="certification",
    ),
]


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_identity_fields(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    assert entity.name == name
    assert entity.url_collection == url_collection
    assert entity.id_param == id_param
    assert entity.model is model


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_parent_is_provider_entity(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    assert entity.parent is PROVIDER_ENTITY


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_audit_binding(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    assert entity.audit is not None
    assert entity.audit.type == name
    create_action, update_action, delete_action = audit_actions
    assert entity.audit.create is create_action
    assert entity.audit.update is update_action
    assert entity.audit.delete is delete_action


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_routes_opted_in(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    """Subrow CRUD only — no independent list/detail/form pages."""
    assert entity.routes == RouteSet(create=True, update=True, delete=True)


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_cls,update_cls",
    CREDENTIALS,
)
def test_adapters_wrap_the_schema_classes(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_cls,
    update_cls,
):
    """Specs pass Pydantic classes; the spec constructor wraps each in
    `TypeAdapter(...)`. Verify the resulting adapter targets the right
    class — the wrapping behavior itself is unit-tested in
    `test_entity_spec.py`."""
    assert isinstance(entity.create_adapter, TypeAdapter)
    assert isinstance(entity.update_adapter, TypeAdapter)
    assert _adapter_target_class(entity.create_adapter) is create_cls
    assert _adapter_target_class(entity.update_adapter) is update_cls


def _adapter_target_class(adapter: TypeAdapter) -> type:
    """Walk a TypeAdapter's core_schema to find the underlying model
    class. PartialUpdate-derived schemas inherit a `model_validator`
    which wraps the model in a `function-after` schema; the inner
    schema carries the `cls`. Plain `BaseModel` subclasses have it at
    the top level."""
    schema = adapter.core_schema
    while schema.get("type") != "model":
        schema = schema["schema"]
    return schema["cls"]


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_write_authz_is_assert_owner_or_admin(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    assert entity.write_authz is assert_owner_or_admin


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_can_write_is_is_owner_or_admin(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    """Predicate sibling of `write_authz` — read by detail handlers for
    `can_edit` flags so the rule lives in exactly one place."""
    assert entity.can_write is is_owner_or_admin


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_redirects_target_parent_form(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    """Sub-row mutations send HTMX clients back to the parent edit form."""
    target = "/providers/abc-123/form"
    assert entity.create_redirect(provider_id="abc-123") == target
    assert entity.update_redirect(provider_id="abc-123") == target
    assert entity.delete_redirect(provider_id="abc-123") == target


@pytest.mark.parametrize(
    "entity,name,url_collection,id_param,model,audit_actions,create_adapter,update_adapter",
    CREDENTIALS,
)
def test_to_resource_spec_walks_parent_chain(
    entity,
    name,
    url_collection,
    id_param,
    model,
    audit_actions,
    create_adapter,
    update_adapter,
):
    rs = entity.to_resource_spec()
    assert rs.collection == url_collection
    assert rs.parent is not None
    assert rs.parent.collection == "providers"
    assert rs.parent.id_param == "provider_id"
