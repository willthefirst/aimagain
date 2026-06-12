"""Per-spec hook callables for the `Program` entity.

Two callables, mirroring :mod:`src.domain.logic.clinicians.handlers`:

* :func:`program_form_extras` — driven by
  ``PROGRAM_ENTITY.form_extras_path``. Loads the requesting user's
  visible Organizations into the form context so the create / edit
  form can render an Org-picker scoped to Orgs the user owns. On
  edit, re-includes the row's currently-attached Org when it would
  otherwise be missing from the visible set.
* :func:`_assert_program_payload_org_ownership` — driven by
  ``PROGRAM_ENTITY.payload_authz_path``. Wire-side authorization on
  the cross-entity FK: the user may only attach a Program to an Org
  they own (superusers bypass; nonexistent Org → 404 with no info
  leak about other users' Org ids). Built from
  :func:`~src.framework.access.authz.authz.make_fk_ownership_payload_authz`
  — the per-entity wrapper is now a one-line factory call.

No bespoke CRUD handlers — the framework's factory-built
``handle_create`` / ``handle_update`` / etc. consume both hooks via
the spec's dotted-path declarations, so the route file is a single
:func:`mount_entity` call.
"""

import logging
from typing import Any

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import (
    Organization,
    Program,
    User,
)
from src.framework.access.authz.authz import (
    list_picker_options_for,
    make_fk_ownership_payload_authz,
)

logger = logging.getLogger(__name__)


# `PROGRAM_ENTITY.payload_authz_path` target — see the factory's docstring
# for the contract. Module-level binding so the spec's dotted import
# resolves.
_assert_program_payload_org_ownership = make_fk_ownership_payload_authz(
    attr="org_id",
    parent_model=Organization,
    parent_noun="Organization",
    child_noun="Program",
    parent_repo_kwarg="organization_repo",
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
    current attachment doesn't exist. The framework helper
    `list_picker_options_for` owns this re-include rule for every
    parent-Org picker.
    """
    return {
        "organizations": await list_picker_options_for(
            organization_repo,
            requesting_user,
            Organization,
            attached_id=target.org_id if target is not None else None,
        )
    }
