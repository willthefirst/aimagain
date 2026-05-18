from src.domain.specs.user import USER_ENTITY
from src.framework.dispatch.registry import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(USER_ENTITY)


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
