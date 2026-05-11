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

from pydantic import BaseModel, TypeAdapter

from src.api.common.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
)
from src.repositories.dependencies import get_provider_repository
from src.specs.provider import PROVIDER_ENTITY, _provider_form_redirect


def make_provider_credential_entity(
    *,
    name: str,
    url_collection: str,
    id_param: str,
    model: type,
    audit_stem: str,
    read_schema: type[BaseModel],
    create_adapter: type[BaseModel] | TypeAdapter,
    update_adapter: type[BaseModel] | TypeAdapter,
) -> EntitySpec:
    """Build a credential-subentity `EntitySpec` from its varying pieces.

    `audit_stem` is the `AuditAction` enum stem (e.g. `"licensure"` for
    the `CREATE_LICENSURE` / `UPDATE_LICENSURE` / `DELETE_LICENSURE`
    triple) — the credential enum stems diverge from the entity `name`
    (which is `"provider_licensure"`) so the stem is passed explicitly
    via the spec's `audit_action_stem`.
    `read_schema` is the response shape for `PATCH`; the spec
    constructor synthesizes `read_to_dict` from it and defaults
    `audit_snapshot` to it as well (credential audit snapshots are
    byte-identical to their read projection).
    """

    return EntitySpec(
        name=name,
        url_collection=url_collection,
        id_param=id_param,
        model=model,
        parent=PROVIDER_ENTITY,
        repo_dep=get_provider_repository,
        auth_deps=AUTHENTICATED,
        auth_policy=OWNER_OR_ADMIN,
        audit_action_stem=audit_stem,
        create_adapter=create_adapter,
        update_adapter=update_adapter,
        read_schema=read_schema,
        # Subrow CRUD only — sub-rows aren't independently listed or
        # detailed (they only appear in the parent provider's pages).
        routes=RouteSet(create=True, update=True, delete=True),
        # Sub-row mutations send HTMX clients back to the parent edit
        # form so the user can keep editing.
        create_redirect=_provider_form_redirect,
        update_redirect=_provider_form_redirect,
        delete_redirect=_provider_form_redirect,
    )
