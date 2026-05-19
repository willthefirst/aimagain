"""`REFERRAL_ENTITY` — the kind-locked face for ``/referrals``."""

from typing import Final

from src.domain.logic.posts.schema import ReferralCreate, ReferralUpdate
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

REFERRAL_ENTITY: Final[EntitySpec] = _post_face(
    name="referral",
    url_collection="referrals",
    kind="referral",
    create_adapter=ReferralCreate,
    update_adapter=ReferralUpdate,
)
