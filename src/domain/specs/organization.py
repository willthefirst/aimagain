"""`ORGANIZATION_ENTITY`: standalone directory entity for clinics, group
practices, health systems, and solo-practice shells.
"""

from typing import Final

from src.domain.logic.organizations.repository import (
    OrganizationRepository,
    get_organization_repository,
)
from src.domain.logic.organizations.schema import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
    OrganizationVerificationAuditSnapshot,
    OrganizationVerificationStateUpdate,
)
from src.domain.models import Organization
from src.domain.models.enums import (
    ORGANIZATION_TYPES,
    ORGANIZATION_TYPES_LABELS,
)
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
    StateAxis,
)

_organization_form_redirect = Redirects.to_edit_form("organizations", "organization_id")


ORGANIZATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="organization",
    url_collection="organizations",
    id_param="organization_id",
    model=Organization,
    repo_dep=get_organization_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=OrganizationCreate,
    update_adapter=OrganizationUpdate,
    read_schema=OrganizationRead,
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    list_order_by=Organization.created_at.desc(),
    create_redirect=_organization_form_redirect,
    update_redirect=_organization_form_redirect,
    # Opt into the HX-Request re-render-on-validation-failure path —
    # see `EntitySpec.form_error_render`. On a Pydantic 422 the
    # framework re-renders `organizations/_form_new_fragment.html`
    # with `form_errors` / `form_values` injected; the form-field
    # macros auto-resolve from those keys (the form template imports
    # them `with context`).
    form_error_render=True,
    # The create/edit form's parent-Org picker is scoped per-viewer to
    # the user's owned Organizations (superusers see all). Replaces the
    # free-text UUID input — see issue #581. The framework invokes the
    # extras callable on both the create path (target=None) and the
    # edit path (target=<row>); the edit path excludes the row being
    # edited from the options so the picker can't pin a self-loop.
    form_extras_path=(
        "src.domain.logic.organizations.handlers.organization_form_extras"
    ),
    form_extras_repos=(("organization_repo", OrganizationRepository),),
    # Templates pull dropdown labels from the spec — same pattern as
    # `CLINICIAN_ENTITY.static_context` for credential vocabularies.
    static_context={
        "ORGANIZATION_TYPES": ORGANIZATION_TYPES,
        "ORGANIZATION_TYPES_LABELS": ORGANIZATION_TYPES_LABELS,
    },
    state_axes=(
        # Admin override of `Organization.npi_match_status`. Mirror of
        # the clinician-side axis (handler/semantics in
        # `src.domain.logic.organizations.handlers.handle_set_org_verification_state`).
        StateAxis(
            name="verification",
            body_schema=OrganizationVerificationStateUpdate,
            action=AuditAction.SET_ORG_VERIFICATION_STATE,
            handler_path=(
                "src.domain.logic.organizations.handlers."
                "handle_set_org_verification_state"
            ),
            audit_snapshot=OrganizationVerificationAuditSnapshot,
            forbid_self=False,
        ),
    ),
)
