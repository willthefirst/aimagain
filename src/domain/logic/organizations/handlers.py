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
from uuid import UUID

from pydantic import BaseModel

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Organization, User
from src.framework.audit.repository import AuditRepository
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


async def handle_set_org_verification_state(
    organization_id: UUID,
    payload: BaseModel,
    repo: OrganizationRepository,
    verification_repo: VerificationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
):
    """Admin-only state-axis handler for
    `PUT /organizations/{id}/verification`. Mirror of the clinician-
    side admin override — flips `Organization.npi_match_status` to
    `matched` / `mismatch` / `pending` and recomputes the Claim-B
    cache.

    See `handle_set_clinician_verification_state` for the rationale
    and the per-state semantics; the only behavioral difference is
    that orgs have no licensure recompute step (Claim B is purely
    NPI-driven)."""
    from datetime import datetime, timezone

    from src.domain.logic.verifications.events import record_verification_event
    from src.domain.logic.verifications.handlers import recompute_org_claim
    from src.domain.specs.organization import ORGANIZATION_ENTITY
    from src.framework.audit.core import record_audit
    from src.framework.http.exceptions import ForbiddenError, NotFoundError

    if not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Setting organization verification state is admin-only"
        )

    org = await repo.get_by_model_id(Organization, organization_id)
    if org is None:
        raise NotFoundError(detail="Organization not found")

    axis = ORGANIZATION_ENTITY.state_axis("verification")
    snapshot = axis.audit_snapshot_fn
    before = snapshot(org)

    target_state = payload.state
    org.npi_match_status = target_state
    if target_state == "matched":
        org.verified_at = datetime.now(timezone.utc)
        verification_event = "admin_verify"
    elif target_state == "mismatch":
        verification_event = "admin_suspend"
    else:
        org.verified_at = None
        verification_event = None

    recompute_org_claim(org)

    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=ORGANIZATION_ENTITY.audit.type,
        resource_id=org.id,
        action=axis.action,
        before=before,
        after=snapshot(org),
    )
    if verification_event is not None:
        await record_verification_event(
            verification_repo=verification_repo,
            audit_repo=audit_repo,
            subject_type="organization",
            org_id=org.id,
            event_type=verification_event,
            status="verified" if target_state == "matched" else "failed",
            evidence={"actor_id": str(requesting_user.id)},
            actor_id=requesting_user.id,
        )
    await repo.session.commit()
    logger.info(
        "organization.verification: id=%s state=%s actor=%s",
        org.id,
        target_state,
        requesting_user.id,
    )
    return org
