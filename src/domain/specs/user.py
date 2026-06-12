"""`USER_ENTITY`: the single declaration of the user resource.

Read by:
  - `src/domain/routes/users.py` — derives `USER_SPEC` for the mount
    helpers and reads the activation state-axis shape.
  - `src/logic/users/user_processing.py` — reads `USER_ENTITY.audit`
    for the `mutate(...)` resource binding,
    `USER_ENTITY.private_fields` and
    `USER_ENTITY.private_field_predicate` for the user-detail
    projection, and `USER_ENTITY.state_axis("activation").action`
    for the activation audit row.

The related-list subresource references `CLINICIAN_ENTITY` from
`src.domain.specs.clinician` — the cross-spec reference stays
inside `specs/` so the layer-direction inversion that
A1 documented (`api/common -> api/routes`) is resolved.
"""

from typing import Final

from src.auth_config import current_active_user
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.users.repository import get_user_repository
from src.domain.logic.users.schema import (
    UserActivationAuditSnapshot,
    UserActivationUpdate,
    UserAuditSnapshot,
)
from src.domain.models import User
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.framework.access.authz.authz import assert_self_or_admin, is_self_or_admin
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import (
    ADMIN_FOR_WRITE,
    EntitySpec,
    RelatedListSubresource,
    RouteSet,
    StateAxis,
)


def _activation_response_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "is_active": user.is_active,
    }


USER_ENTITY: Final[EntitySpec] = EntitySpec(
    name="user",
    url_collection="users",
    id_param="user_id",
    model=User,
    owner_attr=None,  # the resource *is* the user; not owned by another user
    display_label_fn=lambda u: u.username,
    repo_dep=get_user_repository,
    auth_deps=ADMIN_FOR_WRITE,
    # Privacy boundary: non-admins may only see their own user row. The
    # detail page is gated per-row via `detail_authz` (403 for non-self,
    # non-admin viewers); the list is filtered at the repo so non-admins
    # get exactly `[viewer]` back from `list_users` (see `UserRepository`).
    # `read_policy` would be wrong here — it's type-scoped and not called
    # from `_get_by_id`, so it can't gate the detail page.
    detail_authz=lambda target, actor: assert_self_or_admin(
        target, actor, action="view this user"
    ),
    audit_snapshot=UserAuditSnapshot,
    private_fields=("email", "is_active"),
    private_field_predicate=is_self_or_admin,
    public_fields=("id", "username"),
    # Do not exclude self: non-admins now see ONLY self, and admins see all.
    # The viewer's own row must remain in the list for non-admin viewers.
    list_exclude_self=False,
    list_order_by=User.username,
    routes=RouteSet(list=True, detail=True, delete=True),
    # The user-list page is for *other* users; admins can't delete their
    # own account via this endpoint, and the activation state-axis has
    # the same self-target guard. Both are spec-declared so the user
    # cluster doesn't carry hand-written self-target boilerplate.
    delete_forbid_self=True,
    state_axes=(
        StateAxis(
            name="activation",
            body_schema=UserActivationUpdate,
            action=AuditAction.SET_USER_ACTIVATION,
            response_to_dict=_activation_response_to_dict,
            handler_path=("src.domain.logic.users.handlers.handle_set_user_activation"),
            audit_snapshot=UserActivationAuditSnapshot,
            forbid_self=True,
        ),
    ),
    subresources=(
        RelatedListSubresource(
            child_spec=CLINICIAN_ENTITY.to_resource_spec(),
            template="users/clinicians_list.html",
            singleton_alias=("me", current_active_user),
            handler_path=(
                "src.domain.logic.clinicians.handlers.handle_list_user_clinicians"
            ),
        ),
    ),
    # `/users/me` — detail page id sourced from the session.
    singleton_alias=("me", current_active_user),
    # Per-viewer detail extras live on the spec via the same late-bind
    # dotted-path trick the state-axis / subresource handlers use —
    # `specs/user.py` never statically imports `src.logic.users`.
    detail_extras_path="src.domain.logic.users.handlers.user_detail_extras",
    detail_extras_repos=(("clinician_repo", ClinicianRepository),),
)
