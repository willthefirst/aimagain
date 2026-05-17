"""`ORGANIZATION_ENTITY`: PR 1 of the Org/Program roadmap (#516).

Standalone directory entity for clinics, group practices, health
systems, and solo-practice shells. No Provider-side relationships yet —
that lands in PR 2 (Provider.org_id).

Read by:
  - `src/domain/routes/organizations.py` — single `mount_entity` call.
  - `src/framework/audit/test_audit_action_drift.py` — pins that the
    spec's CRUD audit triple is declared on `AuditAction`.
"""

from typing import Final

from src.domain.logic.organizations.schema import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from src.domain.models import Organization
from src.domain.models.enums import (
    ORGANIZATION_TYPES,
    ORGANIZATION_TYPES_LABELS,
)
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)
from src.framework.persistence.dependencies import get_organization_repository

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
    # Templates pull dropdown labels from the spec — same pattern as
    # `PROVIDER_ENTITY.static_context` for credential vocabularies.
    static_context={
        "ORGANIZATION_TYPES": ORGANIZATION_TYPES,
        "ORGANIZATION_TYPES_LABELS": ORGANIZATION_TYPES_LABELS,
    },
)
