from src.api.common import make_entity_router
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.post import POST_ENTITY
from src.logic.posts.post_processing import handle_get_post_form

router = make_entity_router(POST_ENTITY)
posts_api_router = router.router


# Every standard verb (list, detail, create, update, delete, form_edit)
# is factory-built. `list` auto-binds via `make_list_handler(POST_ENTITY)`
# with `post_list_extras` (declared on the spec via `list_extras_path`)
# adding the registered `post_kinds` to the context so the list page
# can render its per-kind 'New X' links. `form_new` stays bespoke for
# the `?kind=` template dispatch.
mount_entity(
    router,
    POST_ENTITY,
    handlers={
        "form_new": handle_get_post_form,
    },
)
