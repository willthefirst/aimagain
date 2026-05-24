"""`REFERRAL_ENTITY` — the kind-locked face for ``/referrals``."""

from typing import Final

from src.domain.logic.posts.schema import ReferralCreate, ReferralUpdate
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

# `form_error_render=True` opts the referral face into the HX-Request
# re-render-on-validation-failure path. The referral form's `_form.html`
# imports `_shared/form_fields.html` macros `with context`, so each
# `field_for(...)` callsite auto-resolves its `error=` / `current=`
# from the `form_errors` / `form_values` mount_create injects on a
# validation-failure re-render — no per-field threading required. See
# `EntitySpec.form_error_render` for the full contract.
REFERRAL_ENTITY: Final[EntitySpec] = _post_face(
    name="referral",
    url_collection="referrals",
    kind="referral",
    create_adapter=ReferralCreate,
    update_adapter=ReferralUpdate,
    form_error_render=True,
)
