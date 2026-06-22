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

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic.clinician_affiliations.repository import (
    ClinicianAffiliationRepository,
)
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Organization, User
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import NotFoundError

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


async def handle_list_org_members(
    request: Request,
    organization_id: UUID,
    repo: ClinicianAffiliationRepository,
    organization_repo: OrganizationRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """`GET /organizations/{id}/members` — the org's affiliated clinicians.

    The "Members" surface from the I6 redesign (#1524): the same
    `(clinician × org)` `ClinicianAffiliation` join that's edited from the
    clinician side, listed here by `org_id`. "One join, two doors" — this
    page is the org's read door onto the members; add / edit / remove
    route through `/clinicians/{id}/clinician_affiliations` because the
    affiliation is FK-owned by the clinician. `mount_related_list` hands
    this handler the *child's* repo (the affiliation repo) under `repo`;
    `organization_repo` loads the parent org for the 404 / breadcrumb.
    """
    org = await organization_repo.get_by_model_id(Organization, organization_id)
    if org is None:
        raise NotFoundError(detail=f"Organization {organization_id} not found")
    page_number = parse_page(request)
    per_page = DEFAULT_PAGE_SIZE
    rows_plus_one = await repo.list_org_members(
        organization_id,
        offset=offset_for(page_number, per_page),
        limit=per_page + 1,
    )
    rows, page = paginate(rows_plus_one, page=page_number, per_page=per_page)
    return {
        "request": request,
        "organization": org,
        "rows": rows,
        "is_self": org.owner_id == requesting_user.id,
        "current_user": requesting_user,
        "pager": Pager(page=page, base_query=base_query(request)),
    }


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
    `POST /profile/org` and now run on the canonical create:

    1. Grant the creating user an immediately-verified owner
       `OrgRepresentation` (shared `grant_owner_representation` — see its
       docstring for why self-create needs no review).
    2. Run the Claim-B NPPES verification inline against the org's
       Type-2 `npi` (now required at the schema layer — see
       `OrganizationCreate.npi: RequiredNpiText`). The pipeline runs
       with `commit=False` so its writes participate in the create
       transaction; if NPPES doesn't return `status='verified'`, a
       `BadRequestError` is raised and the still-uncommitted org row
       (plus the owner `OrgRepresentation` granted in step 1) is
       rolled back by SQLAlchemy when the session exits. An
       organization is never durable without a verified NPI.

    Runs inside the framework's `mutate(...)` block. `payload` is
    accepted for the framework's hook signature but unused — everything
    is read off `row`.
    """
    import httpx

    from src.domain.logic.org_representations.handlers import (
        grant_owner_representation,
    )
    from src.domain.logic.verifications.handlers import (
        HTTP_TIMEOUT_SECONDS,
        npi_failure_message,
        run_org_verification,
    )
    from src.framework.http.exceptions import BadRequestError

    await grant_owner_representation(
        user_id=requesting_user.id,
        org_id=row.id,
        org_rep_repo=org_rep_repo,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        verification = await run_org_verification(
            org_id=row.id,
            verification_repo=verification_repo,
            org_repo=organization_repo,
            audit_repo=verification_audit_repo,
            http=http,
            actor_id=requesting_user.id,
            commit=False,
        )
    if verification.status != "verified":
        raise BadRequestError(detail=npi_failure_message(verification))
    # No `session.refresh(row)` — see the same comment in
    # `after_create_clinician_verification`. `commit=False` leaves the
    # `npi_match_status` / `verified_at` / `authorized_official_name`
    # writes in memory, and `refresh` without autoflush would silently
    # revert them before `mutate(...)` reads the after-snapshot.


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
