from src.domain.specs.posts import REFERRAL_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(REFERRAL_ENTITY)


# Kind-locked face of the polymorphic post entity — the framework
# scopes every verb (list, detail, create, update, delete, form_new,
# form_edit, search) to `kind='referral'` via
# `EntitySpec.discriminator_value`. The picker step that the
# `/posts/form` URL used to render is absent here; ``/referrals/form``
# goes straight to the create form.
mount_entity(router, REFERRAL_ENTITY)
