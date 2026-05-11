import logging

from src.api.common.specs.post import POST_ENTITY
from src.schemas.posts.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
)

logger = logging.getLogger(__name__)

PostCreatePayload = ClientReferralCreate | ProviderAvailabilityCreate
PostUpdatePayload = ClientReferralUpdate | ProviderAvailabilityUpdate


# Audit binding lives on the spec (single declaration). Re-exported as
# `POST` so handler bodies can keep their `resource=POST` shape.
POST = POST_ENTITY.audit
