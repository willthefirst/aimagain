"""`OPENING_ENTITY` — the kind-locked face for ``/openings``."""

from typing import Final

from src.domain.logic.posts.schema import ClinicianOpeningCreate, ClinicianOpeningUpdate
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

OPENING_ENTITY: Final[EntitySpec] = _post_face(
    name="opening",
    url_collection="openings",
    kind="clinician_opening",
    create_adapter=ClinicianOpeningCreate,
    update_adapter=ClinicianOpeningUpdate,
)
