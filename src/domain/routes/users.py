from src.domain.logic.saved_searches.handlers import handle_list_saved_searches
from src.domain.specs.saved_search import SAVED_SEARCH_ENTITY  # noqa: F401
from src.domain.specs.user import USER_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(USER_ENTITY)


# Every verb is factory-built or spec-resolved:
#   - list / detail / delete — auto-bound from `make_<verb>_handler(USER_ENTITY)`.
#     `delete` honors `USER_ENTITY.delete_forbid_self=True` for the
#     "admin can't delete self" rule.
#   - activation — state-axis handler resolved via the spec's
#     `handler_path`; the framework wraps it with the `forbid_self`
#     self-target guard declared on the axis.
#   - clinicians — related-list subresource, same `handler_path` path.
# Detail extras (`user_detail_extras` + the clinician repo it needs)
# live on the spec via `detail_extras_path`.
#
# Owned subentity — saved searches (1:N, FK to `users.id`) self-register
# on `USER_ENTITY.children` at spec-construction time (the spec declares
# `parent=USER_ENTITY`). `mount_entity` defaults
# `owned_subentities=entity.children`, so the `noqa: F401` import above is
# what triggers that registration; create / update / delete / form_new /
# form_edit auto-bind to the factory makers. The `list` verb is bespoke:
# the generic list mount doesn't gate by parent and a saved search is
# private, so it's wired to `handle_list_saved_searches` (self-or-admin
# gate) through `owned_handlers`.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "saved_search.list": handle_list_saved_searches,
    },
)
