from src.api.common import make_entity_router
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic.users.user_processing import (
    handle_delete_user,
    handle_list_users,
)

router = make_entity_router(USER_ENTITY)
# Re-export the underlying APIRouter under the historic name so
# `main.py`'s `app.include_router(users.users_api_router, ...)` keeps
# resolving without churn.
users_api_router = router.router


# `handle_delete_user` and `handle_list_users` are bespoke (self-guard
# on delete; per-viewer admin flag on list). Detail, state-axis
# (`activation`), related-list subresource (`providers`), and per-viewer
# detail extras (`user_detail_extras` + the provider repo it needs) all
# live on `USER_ENTITY` — resolved at mount time via the spec's dotted
# `*_path` strings so `specs/user.py` never imports `src.logic`.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "delete": handle_delete_user,
    },
)
