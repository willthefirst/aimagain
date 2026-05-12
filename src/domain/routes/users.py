from src.domain.specs.user import USER_ENTITY
from src.framework import make_entity_router
from src.framework.resource_routes import mount_entity

router = make_entity_router(USER_ENTITY)
# Re-export the underlying APIRouter under the historic name so
# `main.py`'s `app.include_router(users.users_api_router, ...)` keeps
# resolving without churn.
users_api_router = router.router


# Every verb is factory-built or spec-resolved:
#   - list / detail / delete — auto-bound from `make_<verb>_handler(USER_ENTITY)`.
#     `delete` honors `USER_ENTITY.delete_forbid_self=True` for the
#     "admin can't delete self" rule.
#   - activation — state-axis handler resolved via the spec's
#     `handler_path`; the framework wraps it with the `forbid_self`
#     self-target guard declared on the axis.
#   - providers — related-list subresource, same `handler_path` path.
# Detail extras (`user_detail_extras` + the provider repo it needs)
# live on the spec via `detail_extras_path`.
mount_entity(router, USER_ENTITY, handlers={})
