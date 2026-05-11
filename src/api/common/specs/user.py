"""`USER_ENTITY`: the single declaration of the user resource.

Read by:
  - `src/api/routes/users.py` — derives `USER_SPEC` for the mount
    helpers and reads the activation state-axis shape.
  - `src/logic/users/user_processing.py` — reads `USER_ENTITY.audit`
    for the `mutate(...)` resource binding,
    `USER_ENTITY.private_fields` and
    `USER_ENTITY.private_field_predicate` for the user-detail
    projection, and `USER_ENTITY.state_axis("activation").action`
    for the activation audit row.

The related-list subresource references `PROVIDER_ENTITY` from
`src.api.common.specs.provider` — the cross-spec reference stays
inside `api/common/specs/` so the layer-direction inversion that
A1 documented (`api/common -> api/routes`) is resolved.
"""

from typing import Final

from src.api.common.entity_spec import (
    EntitySpec,
    RelatedListSubresource,
    RouteSet,
    StateAxis,
)
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.auth_config import current_active_user, current_admin_user
from src.logic._authz import is_self_or_admin
from src.logic.audit import AuditAction
from src.models import User
from src.repositories.dependencies import get_user_repository
from src.repositories.providers.provider_repository import ProviderRepository
from src.schemas.users.user import UserActivationUpdate, UserAuditSnapshot


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
    repo_dep=get_user_repository,
    read_user_dep=current_active_user,
    write_user_dep=current_admin_user,
    audit_snapshot=UserAuditSnapshot,
    private_fields=("email", "is_active", "is_verified"),
    private_field_predicate=is_self_or_admin,
    routes=RouteSet(list=True, detail=True, delete=True),
    state_axes=(
        StateAxis(
            name="activation",
            body_schema=UserActivationUpdate,
            action=AuditAction.SET_USER_ACTIVATION,
            response_to_dict=_activation_response_to_dict,
            handler_path=("src.logic.users.user_processing.handle_set_user_activation"),
        ),
    ),
    subresources=(
        RelatedListSubresource(
            child_spec=PROVIDER_ENTITY.to_resource_spec(),
            template="users/providers_list.html",
            singleton_alias=("me", current_active_user),
            handler_path=(
                "src.logic.providers.provider_processing.handle_list_user_providers"
            ),
        ),
    ),
    # `/users/me` — detail page id sourced from the session.
    singleton_alias=("me", current_active_user),
    # Per-viewer detail extras live on the spec via the same late-bind
    # dotted-path trick the state-axis / subresource handlers use —
    # `specs/user.py` never statically imports `src.logic.users`.
    detail_extras_path="src.logic.users.user_processing.user_detail_extras",
    detail_extras_repos=(("provider_repo", ProviderRepository),),
)
