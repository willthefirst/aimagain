"""Per-spec hook callables for the `Post` entity.

`_assert_post_payload_authz` is the entry point driven by
``POST_ENTITY.payload_authz_path``: it layers FK-ownership (the
submitter must own the cross-entity row the post references) AND the
capability gate from the two-claim verification model (a referral / a
clinician-opening requires Claim A; a program-intake requires Claim B
for the org behind the referenced Program).

Why it dispatches on ``payload.kind``: all three kinds reference a
cross-entity FK the submitting user must own.
``clinician_opening.clinician_id`` and ``program_intake.program_id``
point at rows the user created; ``referral.referring_clinician_id``
points at a Clinician the user owns. The cleaner long-term shape is
per-kind authz on :class:`PostKindSpec`; a type-switching dispatcher is
acceptable while the kind set is small.
"""

import logging

from pydantic import BaseModel

from src.domain.logic import capabilities
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.models import Clinician, Program, User
from src.framework.authz import assert_fk_ownership
from src.framework.http.exceptions import ForbiddenError

logger = logging.getLogger(__name__)

# Per-kind mapping for the FK-ownership check. Each entry says: when the
# payload's `kind` matches, validate that the named attribute points at a
# row of `model` (loaded via `repo`) that the requesting user owns.
_KIND_FK_TARGETS: tuple[tuple[str, str, str, type], ...] = (
    # (kind, attr, parent_noun, parent_model)
    ("clinician_opening", "clinician_id", "Clinician", Clinician),
    ("program_intake", "program_id", "Program", Program),
    ("referral", "referring_clinician_id", "Clinician", Clinician),
)


async def _assert_post_payload_authz(
    *,
    payload: BaseModel,
    requesting_user: User,
    clinician_repo: ClinicianRepository,
    program_repo: ProgramRepository,
) -> None:
    """`POST_ENTITY.payload_authz_path` target — runs the two
    payload-time authorization checks in order:

    1. **Ownership** — the per-kind FK on the payload must point at a
       row the requesting user owns. (Existing rule.)
    2. **Capability** — the submitter must hold the claim that gates
       this post-kind:

       - ``referral`` / ``clinician_opening`` → Claim A
         (`capabilities.clinician_verified(user)`).
       - ``program_intake`` → Claim B for the referenced Program's org
         (deferred — the org lookup lands when the Profile Hub PR
         (Phase 5) wires the program-intake create flow end-to-end).

    Superusers bypass the capability check the same way they bypass
    ownership — admins act on any row.
    """
    await _assert_post_payload_target_ownership(
        payload=payload,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        program_repo=program_repo,
    )
    _assert_post_payload_capability(payload, requesting_user)


def _assert_post_payload_capability(payload: BaseModel, requesting_user: User) -> None:
    """Per-kind capability gate. Skips for superusers (admin write
    rights override the claim-based gate). For `program_intake`, the
    Claim-B check requires the referenced Program's org id — which is
    a DB read we don't want to add to this payload-time hook. The
    Profile Hub PR (Phase 5) introduces the dedicated program-intake
    create path that takes the org check; this hook stays focused on
    Claim A."""
    if getattr(requesting_user, "is_superuser", False):
        return
    kind = getattr(payload, "kind", None)
    if kind == "referral" and not capabilities.can_post_referral(requesting_user):
        raise ForbiddenError(
            detail=(
                "Posting a referral requires a verified clinician profile "
                "(Claim A). Visit /profile to complete verification."
            ),
        )
    if kind == "clinician_opening" and not capabilities.can_post_opening(
        requesting_user
    ):
        raise ForbiddenError(
            detail=(
                "Posting a clinician opening requires a verified clinician "
                "profile (Claim A). Visit /profile to complete verification."
            ),
        )
    # `program_intake` Claim-B gate is intentionally deferred — see
    # docstring above.


async def _assert_post_payload_target_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    clinician_repo: ClinicianRepository,
    program_repo: ProgramRepository,
) -> None:
    """Reject a Post create/update whose per-kind FK points at a row
    the requesting user doesn't own (superusers bypass).

    Dispatches on ``payload.kind`` via :data:`_KIND_FK_TARGETS`:

    * ``clinician_opening`` — checks ``payload.clinician_id`` against
      ``Clinician.owner_id``.
    * ``program_intake`` — checks ``payload.program_id`` against
      ``Program.owner_id``.
    * ``referral`` — checks ``payload.referring_clinician_id`` against
      ``Clinician.owner_id``.

    404 when the target row doesn't exist (no info leak about other
    users' ids); 403 when it exists but belongs to someone else. PATCH
    payloads where the FK field is None (the PATCH doesn't touch the
    FK) are a no-op — only flow through the ownership check when the
    payload is actually trying to set a new target. Both branches share
    the generic :func:`~src.framework.authz.assert_fk_ownership` helper.

    See module docstring for why the dispatcher lives here rather than
    on :class:`PostKindSpec` per-kind."""
    kind = getattr(payload, "kind", None)
    repos = {
        "clinician_id": clinician_repo,
        "program_id": program_repo,
        "referring_clinician_id": clinician_repo,
    }
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
