# Side-effect import: AuditLog is framework-owned (`framework/audit/log.py`)
# but the class declaration must run before Alembic reads `metadata` here,
# otherwise `audit_log` won't be registered for autogenerate. Direct
# consumers should import from `src.framework.audit.log`, not from here.
from src.framework.audit.log import AuditLog  # noqa: F401
from src.framework.persistence.base_model import Base, BaseModel, metadata

from .clinicians.clinician import Clinician
from .enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    NETWORK_PREFERENCES,
    ORGANIZATION_TYPES,
    US_STATES,
)
from .favorites.user_favorite import UserFavorite
from .organizations.organization import Organization
from .posts.intake_detail import IntakeDetail
from .posts.opening_detail import OpeningDetail
from .posts.post import Post
from .posts.post_kinds import (
    POST_KIND_BY_DETAIL_MODEL,
    POST_KIND_NAMES,
    POST_KINDS,
    PostKindSpec,
)
from .posts.referral_detail import ReferralDetail
from .programs.program import Program
from .providers.provider import Provider
from .providers.provider_certification import ProviderCertification
from .providers.provider_education import ProviderEducation
from .providers.provider_licensure import ProviderLicensure
from .users.user import User
from .verifications.verification import Verification

__all__ = [
    "Base",
    "BaseModel",
    "CLIENT_AGE_GROUPS",
    "Clinician",
    "ReferralDetail",
    "INSURANCE_CARRIERS",
    "LOCATION_AVAILABILITY_OPTIONS",
    "NETWORK_PREFERENCES",
    "ORGANIZATION_TYPES",
    "Organization",
    "POST_KIND_BY_DETAIL_MODEL",
    "POST_KIND_NAMES",
    "POST_KINDS",
    "Post",
    "PostKindSpec",
    "Program",
    "IntakeDetail",
    "OpeningDetail",
    "ProviderCertification",
    "ProviderEducation",
    "ProviderLicensure",
    "Provider",
    "US_STATES",
    "User",
    "UserFavorite",
    "Verification",
    "metadata",
]
