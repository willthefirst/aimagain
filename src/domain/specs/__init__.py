"""Every `EntitySpec` instance lives here, one per module.

This ``__init__`` re-exports each entity spec so other modules can
``from src.domain.specs import ALL_ENTITY_SPECS`` without filesystem
walking. The conformance suite and the audit-drift guard iterate
:data:`ALL_ENTITY_SPECS` directly.

Adding a new entity:

1. Create ``<entity>.py`` next to the others, exporting
   ``<ENTITY>_ENTITY: Final[EntitySpec]``.
2. Add the matching ``from .<entity> import <ENTITY>_ENTITY`` line
   below and the entry to ``ALL_ENTITY_SPECS``.

Forgetting step 2 leaves the spec invisible to the conformance suite
and the audit-drift guard — they iterate this tuple.
"""

from src.framework.dispatch.entity_spec import EntitySpec

from .clinician import CLINICIAN_ENTITY
from .clinician_affiliation import CLINICIAN_AFFILIATION_ENTITY
from .clinician_certification import CERTIFICATION_ENTITY
from .clinician_education import EDUCATION_ENTITY
from .clinician_licensure import LICENSURE_ENTITY
from .org_representation import ORG_REPRESENTATION_ENTITY
from .organization import ORGANIZATION_ENTITY
from .posts import POST_ENTITY
from .program import PROGRAM_ENTITY
from .saved_search import SAVED_SEARCH_ENTITY
from .user import USER_ENTITY
from .user_favorite import FAVORITE_ENTITY

ALL_ENTITY_SPECS: tuple[EntitySpec, ...] = (
    ORGANIZATION_ENTITY,
    POST_ENTITY,
    PROGRAM_ENTITY,
    CLINICIAN_ENTITY,
    CLINICIAN_AFFILIATION_ENTITY,
    CERTIFICATION_ENTITY,
    EDUCATION_ENTITY,
    LICENSURE_ENTITY,
    USER_ENTITY,
    SAVED_SEARCH_ENTITY,
    FAVORITE_ENTITY,
    ORG_REPRESENTATION_ENTITY,
)

__all__ = [
    "CLINICIAN_AFFILIATION_ENTITY",
    "ALL_ENTITY_SPECS",
    "CERTIFICATION_ENTITY",
    "CLINICIAN_ENTITY",
    "EDUCATION_ENTITY",
    "FAVORITE_ENTITY",
    "LICENSURE_ENTITY",
    "ORGANIZATION_ENTITY",
    "ORG_REPRESENTATION_ENTITY",
    "POST_ENTITY",
    "PROGRAM_ENTITY",
    "SAVED_SEARCH_ENTITY",
    "USER_ENTITY",
]
