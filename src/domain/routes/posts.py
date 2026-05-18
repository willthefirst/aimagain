from src.domain.specs.post import POST_ENTITY
from src.framework.dispatch.registry import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(POST_ENTITY)


# Every verb is factory-built. The `post_kinds` tuple the list page
# reads for its per-kind 'New X' links comes from
# `POST_ENTITY.static_context`, merged into the context by the generic
# `handle_list`. `form_new` picks the per-kind create template via the
# `?kind=` query param + `POST_ENTITY.discriminator[kind].create_template`
# (handled inside `make_new_form_handler`).
mount_entity(router, POST_ENTITY)
