"""`INTAKE_ENTITY` — the kind-locked face for ``/intakes``."""

from typing import Final

from src.domain.logic.posts.schema import ProgramIntakeCreate, ProgramIntakeUpdate
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

INTAKE_ENTITY: Final[EntitySpec] = _post_face(
    name="intake",
    url_collection="intakes",
    kind="program_intake",
    create_adapter=ProgramIntakeCreate,
    update_adapter=ProgramIntakeUpdate,
)
