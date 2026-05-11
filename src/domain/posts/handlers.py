import logging

from src.domain.posts.schema import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
)
from src.specs.post import POST_ENTITY

logger = logging.getLogger(__name__)

PostCreatePayload = ClientReferralCreate | ProviderAvailabilityCreate
PostUpdatePayload = ClientReferralUpdate | ProviderAvailabilityUpdate


# Audit binding lives on the spec (single declaration). Re-exported as
# `POST` so handler bodies can keep their `resource=POST` shape.
POST = POST_ENTITY.audit
