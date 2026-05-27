"""Per-spec hook callables for the `Organization` entity.

One callable today:

* :func:`organization_form_extras` — driven by
  ``ORGANIZATION_ENTITY.form_extras_path``. Loads the requesting
  user's visible Organizations into the form context so the
  create / edit form can render a parent-Org picker (replaces the
  free-text UUID input — see issue #581). Mirrors
  :mod:`src.domain.logic.programs.handlers` and
  :mod:`src.domain.logic.clinicians.handlers`: owners see only their
  own Orgs; superusers see every Org.

Edit-path: the Org being edited is excluded from the picker options
so the form can't self-loop (an Org can't be its own parent). Deeper
cycle prevention (a descendant being chosen as the parent) is not
attempted here — the repository's ``_resolve_root_id`` would still
succeed in that case; a follow-up could push a CHECK or a graph walk
if the tree starts seeing real reparent traffic.

No bespoke CRUD handlers: the framework's factory-built
``handle_create`` / ``handle_update`` / etc. consume the hook via
the spec's dotted-path declaration, so the route file stays a single
``mount_entity`` call.
"""

import logging
from typing import Any

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import Organization, User
from src.framework.authz import list_visible_to

logger = logging.getLogger(__name__)


async def organization_form_extras(
    *,
    target: Organization | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer form extras for the create + edit Organization forms.

    Drives the parent-Org picker (issue #581). The framework invokes
    this on both paths:

    * Create (``target=None``): all visible Orgs are picker options;
      the template's default "(root — no parent)" option is selected.
    * Edit (``target=<org row>``): the same visible-Org list, minus
      the row being edited (prevents a self-loop on submit). The
      template pre-selects the row's current ``parent_org_id`` if it
      still appears in the options.
    """
    orgs = await list_visible_to(organization_repo, requesting_user, Organization)
    if target is not None:
        orgs = [o for o in orgs if o.id != target.id]
    return {"parent_org_options": orgs}
