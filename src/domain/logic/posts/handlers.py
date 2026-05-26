"""Per-spec hook callables for the `Post` entity.

One callable today — :func:`_assert_post_payload_target_ownership` —
driven by ``POST_ENTITY.payload_authz_path``. The post entity has no
bespoke CRUD handlers; this hook plus the spec declaration is the
entire wire-side authorization surface for posts.

Why it dispatches on ``payload.kind``: two of the three kinds reference
a cross-entity FK in the payload (``clinician_opening.clinician_id``
points at a Clinician; ``program_intake.program_id`` points at a
Program). Each needs the same "the requesting user must own the target
row" check. The cleaner long-term shape is per-kind authz on
:class:`PostKindSpec` (registry-per-kind ``payload_authz_path``); a
type-switching dispatcher is acceptable while the kind set is small.

``referral`` has no target FK and is intentionally skipped: a
CR post describes a hypothetical client, not a row a third party owns.
"""

import logging

from pydantic import BaseModel

from src.domain.logic.programs.repository import ProgramRepository
from src.domain.logic.providers.repository import ClinicianRepository
from src.domain.models import Clinician, Program, User
from src.framework.authz import assert_fk_ownership

logger = logging.getLogger(__name__)

# Per-kind mapping for the FK-ownership check. Each entry says: when the
# payload's `kind` matches, validate that the named attribute points at a
# row of `model` (loaded via `repo`) that the requesting user owns.
# `referral` is intentionally absent — it has no target FK; the dispatch
# below no-ops for any kind not in this map.
_KIND_FK_TARGETS: tuple[tuple[str, str, str, type], ...] = (
    # (kind, attr, parent_noun, parent_model)
    ("clinician_opening", "clinician_id", "Clinician", Clinician),
    ("program_intake", "program_id", "Program", Program),
)


async def _assert_post_payload_target_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    clinician_repo: ClinicianRepository,
    program_repo: ProgramRepository,
) -> None:
    """``POST_ENTITY.payload_authz_path`` target — reject a Post
    create/update whose per-kind FK points at a row the requesting user
    doesn't own (superusers bypass).

    Dispatches on ``payload.kind`` via :data:`_KIND_FK_TARGETS`:

    * ``clinician_opening`` — checks ``payload.clinician_id`` against
      ``Clinician.owner_id``.
    * ``program_intake`` — checks ``payload.program_id`` against
      ``Program.owner_id``.
    * ``referral`` (and any future kind without a target FK) — no-op.

    404 when the target row doesn't exist (no info leak about other
    users' ids); 403 when it exists but belongs to someone else. PATCH
    payloads where the FK field is None (the PATCH doesn't touch the
    FK) are a no-op — only flow through the ownership check when the
    payload is actually trying to set a new target. Both branches share
    the generic :func:`~src.framework.authz.assert_fk_ownership` helper.

    See module docstring for why the dispatcher lives here rather than
    on :class:`PostKindSpec` per-kind."""
    kind = getattr(payload, "kind", None)
    repos = {"clinician_id": clinician_repo, "program_id": program_repo}
    for target_kind, attr, parent_noun, parent_model in _KIND_FK_TARGETS:
        if kind != target_kind:
            continue
        await assert_fk_ownership(
            payload=payload,
            attr=attr,
            requesting_user=requesting_user,
            parent_repo=repos[attr],
            parent_model=parent_model,
            parent_noun=parent_noun,
            child_noun="post",
        )
        return
    # referral and any future kind without a target FK: no-op.
