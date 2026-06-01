"""`ORG_REPRESENTATION_ENTITY`: User↔Org authority carrier — Claim B.

Per handoff §5.3 and the OrgRepresentation README, this is **not**
`ClinicianAffiliation`. The two co-exist on the same `Organization` and serve
different purposes:

- `ClinicianAffiliation` = Clinician↔Org practice attrs (insurance, modality).
- `OrgRepresentation` = User↔Org authority (role, method, status).

Routes mount as `/org_representations/{id}` (no subresource nesting —
the resource is User-owned, not Org-owned, so a `/orgs/{id}/reps`
shape would be misleading). The `authority` state axis is the
admin (or rep_approval-approver) override of `authority_status`.

Creation uses the generic factory plus an `after_create` hook for the
per-`authority_method` dispatch (auto-verify for `authorized_official`,
record a `Verification` event, etc.) — see
`src.domain.logic.org_representations.handlers.after_create_org_representation`.
The hook runs inside the framework's `mutate(...)` create transaction so
its mutations land in the audit `after` snapshot.
"""

from typing import Final

from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
    get_org_representation_repository,
)
from src.domain.logic.org_representations.schema import (
    OrgRepresentationAuditSnapshot,
    OrgRepresentationAuthorityAuditSnapshot,
    OrgRepresentationAuthorityUpdate,
    OrgRepresentationCreate,
    OrgRepresentationRead,
    OrgRepresentationUpdate,
)
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import OrgRepresentation
from src.framework.audit.core import AuditAction
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
    StateAxis,
)

ORG_REPRESENTATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="org_representation",
    url_collection="org_representations",
    id_param="org_representation_id",
    model=OrgRepresentation,
    # Owner is the user the representation is *for*. Authz reads
    # `OrgRepresentation.user_id` — the user can manage their own row;
    # admins can manage any.
    owner_attr="user_id",
    repo_dep=get_org_representation_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=OrgRepresentationCreate,
    update_adapter=OrgRepresentationUpdate,
    read_schema=OrgRepresentationRead,
    audit_snapshot=OrgRepresentationAuditSnapshot,
    # Generic CRUD through the factory; the per-authority_method
    # dispatch happens in `after_create`. Update + delete are
    # unchanged.
    routes=RouteSet(create=True, update=True, delete=True),
    # Precondition validation: AO name-match check, domain_email stub,
    # rep_approval-approver check. Raises on rejection.
    payload_authz_path=(
        "src.domain.logic.org_representations.handlers."
        "validate_org_representation_payload"
    ),
    payload_authz_repos=(
        # `repo` is already a framework-reserved signature param on the
        # create handler; declare under a distinct name and the hook
        # consumes the same `OrgRepresentationRepository` instance via
        # FastAPI's per-request injection.
        ("org_rep_repo", OrgRepresentationRepository),
    ),
    # Post-persist dispatch: mutates the just-created row's
    # `authority_status` + `approved_by` from `payload.authority_method`,
    # and appends a `Verification` event for auto-verified paths
    # (`authorized_official`, `rep_approval`). Lands inside the
    # framework's create transaction so audit + verification rows
    # commit atomically with the row itself.
    after_create_path=(
        "src.domain.logic.org_representations.handlers."
        "after_create_org_representation"
    ),
    after_create_repos=(
        ("verification_repo", VerificationRepository),
        # `audit_repo` is reserved by the create-handler factory; bind
        # under a distinct name so the hook receives its own injected
        # instance.
        ("audit_repo_dep", AuditRepository),
    ),
    state_axes=(
        StateAxis(
            name="authority",
            body_schema=OrgRepresentationAuthorityUpdate,
            action=AuditAction.SET_ORG_REPRESENTATION_AUTHORITY,
            handler_path=(
                "src.domain.logic.org_representations.handlers."
                "handle_set_org_representation_authority"
            ),
            audit_snapshot=OrgRepresentationAuthorityAuditSnapshot,
            forbid_self=False,
        ),
    ),
)
