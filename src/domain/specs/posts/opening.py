"""`OPENING_ENTITY` — the kind-locked face for ``/openings``."""

from typing import Final

from src.domain.logic.posts.schema import OpeningCreate, OpeningUpdate
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

OPENING_ENTITY: Final[EntitySpec] = _post_face(
    name="opening",
    url_collection="openings",
    kind="opening",
    create_adapter=OpeningCreate,
    update_adapter=OpeningUpdate,
)
