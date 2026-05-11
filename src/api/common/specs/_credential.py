"""Factory for the provider-credential subentity specs.

The three provider credentials (`licensure`, `education`, `certification`)
have identical `EntitySpec` shape — owned subentities of `Provider`,
subrow-CRUD-only routes, parent-form redirect on every mutation,
`assert_owner_or_admin` write_authz against the parent. They differ
only in identity (name/model/id_param), audit-action enums, and schemas.

`make_provider_credential_entity` is the single declaration of the
shared shape; the three spec modules pass the per-credential pieces
through it.
"""

from typing import Any

from pydantic import BaseModel, TypeAdapter

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY, _provider_form_redirect
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin, is_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter
from src.repositories.dependencies import get_provider_repository


def make_provider_credential_entity(
    *,
    name: str,
    url_collection: str,
    id_param: str,
    model: type,
    audit_actions: tuple[AuditAction, AuditAction, AuditAction],
    snapshot_schema: type[BaseModel],
    read_schema: type[BaseModel],
    create_adapter: TypeAdapter,
    update_adapter: TypeAdapter,
) -> EntitySpec:
    """Build a credential-subentity `EntitySpec` from its varying pieces.

    `audit_actions` is a `(create, update, delete)` triple of
    `AuditAction` enum values. `snapshot_schema` is the Pydantic
    schema used for audit before/after snapshots; `read_schema` is
    the response shape for `PATCH` (consumed via `read_to_dict`).
    """

    audited_resource = AuditedResource(
        type=name,
        snapshot=make_snapshotter(snapshot_schema),
        create=audit_actions[0],
        update=audit_actions[1],
        delete=audit_actions[2],
    )

    def read_to_dict(row: Any) -> dict:
        return read_schema.model_validate(row).model_dump(mode="json")

    return EntitySpec(
        name=name,
        url_collection=url_collection,
        id_param=id_param,
        model=model,
        parent=PROVIDER_ENTITY,
        repo_dep=get_provider_repository,
        write_user_dep=current_active_user,
        write_authz=assert_owner_or_admin,
        can_write=is_owner_or_admin,
        audit=audited_resource,
        create_adapter=create_adapter,
        update_adapter=update_adapter,
        read_to_dict=read_to_dict,
        # Subrow CRUD only — sub-rows aren't independently listed or
        # detailed (they only appear in the parent provider's pages).
        routes=RouteSet(create=True, update=True, delete=True),
        # Sub-row mutations send HTMX clients back to the parent edit
        # form so the user can keep editing.
        create_redirect=_provider_form_redirect,
        update_redirect=_provider_form_redirect,
        delete_redirect=_provider_form_redirect,
    )
