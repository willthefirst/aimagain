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
from src.framework.authz import assert_fk_ownership, list_visible_to
from src.framework.http.exceptions import ForbiddenError, NotFoundError  # noqa: F401

logger = logging.getLogger(__name__)


async def _assert_program_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """`PROGRAM_ENTITY.payload_authz_path` target — thin wrapper around
    the framework's generic FK-ownership assertion. Keeps the dotted-
    path on the spec stable while the rule lives in one framework spot.
    """
    await assert_fk_ownership(
        payload=payload,
        attr="org_id",
        requesting_user=requesting_user,
        parent_repo=organization_repo,
        parent_model=Organization,
        parent_noun="Organization",
        child_noun="Program",
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
    orgs = await list_visible_to(organization_repo, requesting_user, Organization)
    if target is not None:
        org_ids = {o.id for o in orgs}
        if target.org_id not in org_ids:
            attached = await organization_repo.get_by_model_id(
                Organization, target.org_id
            )
            if attached is not None:
                orgs = [*orgs, attached]
    return {"organizations": orgs}
