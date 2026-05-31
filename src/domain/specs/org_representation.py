"""`ORG_REPRESENTATION_ENTITY`: User↔Org authority carrier — Claim B.

Per handoff §5.3 and the OrgRepresentation README, this is **not**
`Affiliation`. The two co-exist on the same `Organization` and serve
different purposes:

- `Affiliation` = Clinician↔Org practice attrs (insurance, modality).
- `OrgRepresentation` = User↔Org authority (role, method, status).

Routes mount as `/org_representations/{id}` (no subresource nesting —
the resource is User-owned, not Org-owned, so a `/orgs/{id}/reps`
shape would be misleading). The `authority` state axis is the
admin (or rep_approval-approver) override of `authority_status`.

This Phase-1 spec lands the minimum routes the Profile Hub (Phase 5)
needs: `create` for the goal-led setup flow, `update` for role
changes, `delete` for hard-revoke admin paths. List/detail/form
templates land alongside the Profile Hub partials in Phase 5; until
then the spec opts out of `list` / `detail` / `form_new` / `form_edit`
so no placeholder template is shipped.
"""

from typing import Final

from src.domain.logic.org_representations.repository import (
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
from src.domain.models import OrgRepresentation
from src.framework.audit.core import AuditAction
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
    # Phase 1: API surface only. The Profile Hub (Phase 5) renders the
    # list/detail/form views via its own per-mode partials — no generic
    # collection page here yet, so we don't ship placeholder templates.
    routes=RouteSet(create=True, update=True, delete=True),
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
