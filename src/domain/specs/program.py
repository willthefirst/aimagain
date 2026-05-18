"""`PROGRAM_ENTITY`: PR 4 of the Org/Program roadmap (#537).

A :class:`Program` is a treatment offering owned by an
:class:`Organization`. The spec declares both per-spec hooks
introduced by the prior framework work — ``form_extras_path`` (PR
#534, for the Org-picker dropdown) and ``payload_authz_path`` (PR
#535, for wire-side authorization on the cross-entity FK) — so the
route file stays a single :func:`mount_entity` call with no bespoke
handler overrides. This is the conformance check that PR #534 + #535
fully generalized PR 3's bespoke-handler workaround.

Read by:
  - ``src/domain/routes/programs.py`` — single ``mount_entity`` call.
  - ``src/framework/audit/test_audit_action_drift.py`` — pins that
    the spec's CRUD audit triple is declared on ``AuditAction``.
"""

from typing import Final

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.programs.repository import get_program_repository
from src.domain.logic.programs.schema import (
    ProgramCreate,
    ProgramRead,
    ProgramUpdate,
)
from src.domain.models import Program
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)

_program_form_redirect = Redirects.to_edit_form("programs", "program_id")


PROGRAM_ENTITY: Final[EntitySpec] = EntitySpec(
    name="program",
    url_collection="programs",
    id_param="program_id",
    model=Program,
    repo_dep=get_program_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=ProgramCreate,
    update_adapter=ProgramUpdate,
    read_schema=ProgramRead,
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    list_order_by=Program.created_at.desc(),
    create_redirect=_program_form_redirect,
    update_redirect=_program_form_redirect,
    # The create/edit form's Org-picker is scoped per-viewer to the
    # user's owned Organizations (#537). The framework invokes the
    # extras callable on both the create path (target=None) and the
    # edit path (target=<row>) — see ``EntitySpec.form_extras_path``.
    form_extras_path="src.domain.logic.programs.handlers.program_form_extras",
    form_extras_repos=(("organization_repo", OrganizationRepository),),
    # Wire-side authz: a user may only attach a Program to an Org they
    # own (#537). The framework's ``payload_authz`` hook (PR #535) lets
    # the rule live on the spec instead of duplicating create/update
    # wiring in a bespoke handler.
    payload_authz_path=(
        "src.domain.logic.programs.handlers._assert_program_payload_org_ownership"
    ),
    payload_authz_repos=(("organization_repo", OrganizationRepository),),
)
