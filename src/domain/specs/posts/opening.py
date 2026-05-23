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

# `form_error_render=True` opts this face into the HX-Request
# re-render-on-validation-failure path (see `EntitySpec.form_error_render`
# and `mount_create`). First-pass scope: the clinician_opening form's
# `age_groups` field surfaces an inline error instead of silently
# 422-ing. The form templates in `domain/templates/posts/openings/` are
# wired to consume `form_errors` and `form_values` from the context.
OPENING_ENTITY: Final[EntitySpec] = _post_face(
    name="opening",
    url_collection="openings",
    kinds=("clinician_opening", "program_intake"),
    create_adapter=openings_create_adapter,
    update_adapter=openings_update_adapter,
    form_error_render=True,
)
