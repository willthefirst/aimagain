"""Per-spec hook callables for the `Program` entity.

Two callables, mirroring :mod:`src.domain.logic.providers.handlers`:

* :func:`program_form_extras` — driven by
  ``PROGRAM_ENTITY.form_extras_path``. Loads the requesting user's
  visible Organizations into the form context so the create / edit
  form can render an Org-picker scoped to Orgs the user owns.
* :func:`_assert_program_payload_org_ownership` — driven by
  ``PROGRAM_ENTITY.payload_authz_path``. Wire-side authorization on
  the cross-entity FK: the user may only attach a Program to an Org
  they own (superusers bypass; nonexistent Org → 404 with no info
  leak about other users' Org ids).

No bespoke CRUD handlers — the framework's factory-built
``handle_create`` / ``handle_update`` / etc. consume both hooks via
the spec's dotted-path declarations, so the route file is a single
:func:`mount_entity` call (the conformance check for the framework
generalizations from PRs #534 + #535).
"""

import logging
from typing import Any

from pydantic import BaseModel

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import (
    Organization,
    Program,
    User,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


async def _orgs_visible_to(
    org_repo: OrganizationRepository, user: User
) -> list[Organization]:
    """Return the Organizations a user may attach their Program to.

    Owners see only the Orgs they own; superusers see every Org. Drives
    the Program create/edit form's Org-picker dropdown and pairs with
    the wire-level ownership check in
    :func:`_assert_program_payload_org_ownership`. Mirrors
    ``_orgs_visible_to`` on the Provider side — Org ownership is the
    boundary for who may attach owned children (Providers, Programs)."""
    if user.is_superuser:
        return list(
            await org_repo.list_default(
                Organization, order_by=Organization.created_at.desc()
            )
        )
    return list(await org_repo.list_for_user(user.id))


async def _assert_program_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """`PROGRAM_ENTITY.payload_authz_path` target — reject a Program
    create/update whose ``org_id`` points at an Org the requesting
    user doesn't own (superusers bypass).

    404 when the Org doesn't exist (no info leak about other users' Org
    ids); 403 when it exists but belongs to someone else. PATCH
    payloads where ``org_id`` is None (i.e. the PATCH doesn't touch
    the FK) are a no-op — only flow through the ownership check when
    the payload is actually trying to set a new Org. Same shape as
    :func:`src.domain.logic.providers.handlers._assert_provider_payload_org_ownership`.
    """
    org_id = getattr(payload, "org_id", None)
    if org_id is None:
        return
    org = await organization_repo._get_by_id(Organization, org_id)
    if org is None:
        raise NotFoundError(detail=f"Organization {org_id} not found")
    if not requesting_user.is_superuser and org.owner_id != requesting_user.id:
        raise ForbiddenError(
            detail="You may only attach a Program to an Organization you own"
        )


async def program_form_extras(
    *,
    target: Program | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer form extras for `make_new_form_handler` /
    `make_edit_form_handler` against `PROGRAM_ENTITY`.

    Loads the requesting user's visible Organizations into the context
    for the Org-picker dropdown. The framework invokes this on both
    the create path (``target=None``) and the edit path
    (``target=<program row>``); the template pre-selects the row's
    current ``org_id``.

    Edit-path special case: when the Program's currently-attached Org
    is no longer in the user's owned set (e.g. ownership transferred
    elsewhere, or a superuser is editing someone else's Program), the
    attached Org is still included in the dropdown so the form
    doesn't silently drop the FK on submit. The user can still
    re-point at any other Org they own; they just can't pretend the
    current attachment doesn't exist.
    """
    orgs = await _orgs_visible_to(organization_repo, requesting_user)
    if target is not None:
        org_ids = {o.id for o in orgs}
        if target.org_id not in org_ids:
            attached = await organization_repo._get_by_id(Organization, target.org_id)
            if attached is not None:
                orgs = [*orgs, attached]
    return {"organizations": orgs}
