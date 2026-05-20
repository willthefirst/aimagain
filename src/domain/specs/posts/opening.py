"""`OPENING_ENTITY` — the subset-supertype face for ``/openings``.

Lists posts whose kind is ``clinician_opening`` or ``program_intake``;
create/edit dispatch by `?kind=X` on the URL (same shape the old
whole-supertype `/posts` face used, scoped to two of the three kinds).
``/intakes`` is no longer mounted — program intakes are reached through
``/openings`` like clinician openings are.

`/referrals` stays kind-locked (single-kind family) in its own spec.
"""

from typing import Final

from src.domain.logic.posts.schema import (
    openings_create_adapter,
    openings_update_adapter,
)
from src.framework.dispatch.entity_spec import EntitySpec

from ._base import _post_face

OPENING_ENTITY: Final[EntitySpec] = _post_face(
    name="opening",
    url_collection="openings",
    kinds=("clinician_opening", "program_intake"),
    create_adapter=openings_create_adapter,
    update_adapter=openings_update_adapter,
)
