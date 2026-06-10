"""Factory for the clinician credential subentity specs.

The three clinician credentials (`licensure`, `education`, `certification`)
have identical `EntitySpec` shape — owned subentities of `Clinician`,
subrow-CRUD-only routes, parent-form redirect on every mutation,
`assert_owner_or_admin` write_authz against the parent. They differ
only in identity (name/model/id_param), audit-action enums, and schemas.

`make_clinician_credential_entity` is the single declaration of the
shared shape; the three spec modules pass the per-credential pieces
through it.
"""

from typing import Callable

from pydantic import BaseModel, TypeAdapter

from src.domain.logic.clinicians.repository import get_clinician_repository
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
    StateAxis,
)


def make_clinician_credential_entity(
    *,
    name: str,
    url_collection: str,
    id_param: str,
    model: type,
    audit_stem: str,
    read_schema: type[BaseModel],
    create_adapter: type[BaseModel] | TypeAdapter,
    update_adapter: type[BaseModel] | TypeAdapter,
    mutation_redirect: Callable[..., str],
    state_axes: tuple[StateAxis, ...] = (),
) -> EntitySpec:
    """Build a credential-subentity `EntitySpec` from its varying pieces.

    `audit_stem` is the `AuditAction` enum stem (e.g. `"licensure"` for
    the `CREATE_LICENSURE` / `UPDATE_LICENSURE` / `DELETE_LICENSURE`
    triple) — the credential enum stems diverge from the entity `name`
    (which is `"clinician_licensure"`) so the stem is passed explicitly
    via the spec's `audit_action_stem`.
    `read_schema` is the response shape for `PATCH`; the spec
    constructor synthesizes `read_to_dict` from it and defaults
    `audit_snapshot` to it as well (credential audit snapshots are
    byte-identical to their read projection).

    `mutation_redirect` is the post-create/update/delete redirect
    callable. After #1336 each credential redirects to its own
    list page (`/clinicians/{id}/licensures` etc.) rather than the
    parent's edit form.

    `state_axes` is the per-credential state-axis tuple. Only
    `LICENSURE_ENTITY` uses it today (the `attestation` axis); the
    other two credentials pass `()`. This is the parent-owned
    subentity surface that landed when `mount_state_axis` gained
    `spec.parent`-aware mounting.
    """

    return EntitySpec(
        name=name,
        url_collection=url_collection,
        id_param=id_param,
        model=model,
        parent=CLINICIAN_ENTITY,
        # Default check: `child.clinician_id == URL.clinician_id`
        # (derived from `spec.parent.name` = "clinician"). No override needed.
        repo_dep=get_clinician_repository,
        auth_deps=AUTHENTICATED,
        auth_policy=OWNER_OR_ADMIN,
        audit_action_stem=audit_stem,
        create_adapter=create_adapter,
        update_adapter=update_adapter,
        read_schema=read_schema,
        # Subrow CRUD only. The parent CLINICIAN_ENTITY now owns a
        # `RelatedListSubresource` per credential type (#1336) — the
        # list page is mounted there, not here.
        routes=RouteSet(create=True, update=True, delete=True),
        # Sub-row mutations send HTMX clients back to the sub-resource's
        # own list page so the user keeps managing in place.
        create_redirect=mutation_redirect,
        update_redirect=mutation_redirect,
        delete_redirect=mutation_redirect,
        state_axes=state_axes,
    )
