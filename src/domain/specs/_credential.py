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

_DEFAULT_CREDENTIAL_ROUTES: RouteSet = RouteSet(create=True, update=True, delete=True)

# The canonical resource pattern: dedicated list / form_new / form_edit
# pages on top of the CRUD trio. Once every credential is converted
# this becomes the factory default and `_DEFAULT_CREDENTIAL_ROUTES`
# disappears.
CANONICAL_CREDENTIAL_ROUTES: RouteSet = RouteSet(
    list=True,
    create=True,
    update=True,
    delete=True,
    form_new=True,
    form_edit=True,
)


def make_clinician_credential_entity(
    *,
    name: str,
    singular_label: str,
    url_collection: str,
    id_param: str,
    model: type,
    audit_stem: str,
    read_schema: type[BaseModel],
    create_adapter: type[BaseModel] | TypeAdapter,
    update_adapter: type[BaseModel] | TypeAdapter,
    mutation_redirect: Callable[..., str],
    state_axes: tuple[StateAxis, ...] = (),
    routes: RouteSet = _DEFAULT_CREDENTIAL_ROUTES,
    static_context: dict | None = None,
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

    `routes` defaults to ``RouteSet(create=True, update=True, delete=True)``
    — the minimal subrow-CRUD shape the credential trio shipped on.
    Pass an expanded ``RouteSet`` (e.g. with ``list=True, form_new=True,
    form_edit=True``) for credentials that have been converted to the
    canonical resource pattern (dedicated list + form pages instead of
    inline forms on the parent's edit page). The conversion lands one
    credential at a time; the expanded shape becomes the default once
    every credential has been converted.
    """

    return EntitySpec(
        name=name,
        # The user-visible noun for chrome labels (form-page H1, list
        # toolbar CTA, etc.). The spec `name` is the URL-identifier
        # ("clinician_licensure") and would surface in the UI as the
        # bare snake-case literal without this override. See
        # `src/framework/rendering/labels.py`.
        singular_label=singular_label,
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
        # Default: subrow CRUD only — the parent CLINICIAN_ENTITY owns
        # a `RelatedListSubresource` per credential type (#1336) and
        # mounts the list page there. Credentials converted to the
        # canonical resource pattern pass an expanded ``routes=`` with
        # ``list=True, form_new=True, form_edit=True`` and the parent's
        # ``RelatedListSubresource`` entry for them is removed (no
        # double-mount).
        routes=routes,
        # Sub-row mutations send HTMX clients back to the sub-resource's
        # own list page so the user keeps managing in place.
        create_redirect=mutation_redirect,
        update_redirect=mutation_redirect,
        delete_redirect=mutation_redirect,
        # Per-credential template constants (controlled vocabularies,
        # state lists). Each credential's create/edit/list templates
        # reference its own type tuple + labels and US_STATES; merging
        # them onto the spec's static_context means the templates don't
        # depend on Jinja-global injection.
        static_context=static_context or {},
        state_axes=state_axes,
    )
