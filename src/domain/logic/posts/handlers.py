"""Per-spec hook callables for the `Post` entity.

One callable today — :func:`_assert_post_payload_target_ownership` —
driven by ``POST_ENTITY.payload_authz_path``. The post entity has no
bespoke CRUD handlers; this hook plus the spec declaration is the
entire wire-side authorization surface for posts.

Why it dispatches on ``payload.kind``: two of the three kinds reference
a cross-entity FK in the payload (``opening.provider_id``
points at a Provider; ``program_availability.program_id`` points at a
Program). Each needs the same "the requesting user must own the target
row" check. The cleaner long-term shape is per-kind authz on
:class:`PostKindSpec` (registry-per-kind ``payload_authz_path``); a
type-switching dispatcher is acceptable while the kind set is small.

``referral`` has no target FK and is intentionally skipped: a
CR post describes a hypothetical client, not a row a third party owns.

History: prior to #541 the post entity had **no** wire-side authz on
its FK fields. ``opening.provider_id`` was nominally
"verified at write time" (per the schema docstring) but no handler
implemented the check — a wire-level attacker could post a PA
referencing any Provider's id. This module closes that gap as a
side-effect of generalizing for the new Program kind. See the PR body
for the Step 0 investigation finding.
"""

import logging

from pydantic import BaseModel

from src.domain.logic.programs.repository import ProgramRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.models import Program, Provider, User
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


async def _assert_post_payload_target_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    provider_repo: ProviderRepository,
    program_repo: ProgramRepository,
) -> None:
    """``POST_ENTITY.payload_authz_path`` target — reject a Post
    create/update whose per-kind FK points at a row the requesting user
    doesn't own (superusers bypass).

    Dispatches on ``payload.kind``:

    * ``opening`` — checks ``payload.provider_id`` against
      ``Provider.owner_id``.
    * ``program_availability`` — checks ``payload.program_id`` against
      ``Program.owner_id``.
    * ``referral`` — no target FK; no-op.

    404 when the target row doesn't exist (no info leak about other
    users' ids); 403 when it exists but belongs to someone else. PATCH
    payloads where the FK field is None (the PATCH doesn't touch the
    FK) are a no-op — only flow through the ownership check when the
    payload is actually trying to set a new target.

    See module docstring for why the dispatcher lives here rather than
    on :class:`PostKindSpec` per-kind."""
    kind = getattr(payload, "kind", None)
    if kind == "opening":
        provider_id = getattr(payload, "provider_id", None)
        if provider_id is None:
            return
        provider = await provider_repo._get_by_id(Provider, provider_id)
        if provider is None:
            raise NotFoundError(detail=f"Provider {provider_id} not found")
        if not requesting_user.is_superuser and provider.owner_id != requesting_user.id:
            raise ForbiddenError(
                detail="You may only post availability for a Provider you own"
            )
        return
    if kind == "program_availability":
        program_id = getattr(payload, "program_id", None)
        if program_id is None:
            return
        program = await program_repo._get_by_id(Program, program_id)
        if program is None:
            raise NotFoundError(detail=f"Program {program_id} not found")
        if not requesting_user.is_superuser and program.owner_id != requesting_user.id:
            raise ForbiddenError(
                detail="You may only post availability for a Program you own"
            )
        return
    # referral and any future kind without a target FK: no-op.
