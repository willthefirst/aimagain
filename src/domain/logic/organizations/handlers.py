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

from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Organization, User
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)


async def organization_form_extras(
    *,
    target: Organization | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer form extras for the create + edit Organization forms.

    Returns no extras today — the flat Organization model has no
    relationship the form needs to pre-populate. Kept as the
    ``form_extras_path`` target so the spec wiring stays stable for
    future per-viewer context (e.g. an audit-scoped picker).
    """
    return {}


async def after_create_organization_owner_grant(
    *,
    row: Organization,
    requesting_user: User,
    org_rep_repo: OrgRepresentationRepository,
    verification_repo: VerificationRepository,
    organization_repo: OrganizationRepository,
    verification_audit_repo: AuditRepository,
    payload: BaseModel | None = None,
) -> None:
    """`after_create_path` target for `POST /organizations`.

    Two side effects, both previously living only in the onboarding hub's
    `POST /profile/org` and now run on the canonical create so a
    self-service org registration via `/organizations/form` behaves the
    same:

    1. Grant the creating user an immediately-verified owner
       `OrgRepresentation` (shared `grant_owner_representation` — see its
       docstring for why self-create needs no review).
    2. When the org carries a Type-2 `npi`, run the Claim-B NPPES
       verification inline (symmetric with the clinician NPI path). No
       NPI → `org_verified` stays False, addable later.

    Runs inside the framework's `mutate(...)` block; `run_org_verification`
    commits internally, so the row is refreshed afterwards to keep it
    usable for the audit after-snapshot (mirrors
    `after_create_clinician_verification`). `payload` is accepted for the
    framework's hook signature but unused — everything is read off `row`.
    """
    from src.domain.logic.org_representations.handlers import (
        grant_owner_representation,
    )

    await grant_owner_representation(
        user_id=requesting_user.id,
        org_id=row.id,
        org_rep_repo=org_rep_repo,
    )

    if row.npi:
        import httpx

        from src.domain.logic.verifications.handlers import (
            HTTP_TIMEOUT_SECONDS,
            run_org_verification,
        )

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            await run_org_verification(
                org_id=row.id,
                verification_repo=verification_repo,
                org_repo=organization_repo,
                audit_repo=verification_audit_repo,
                http=http,
                actor_id=requesting_user.id,
            )
        await organization_repo.session.refresh(row)


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
