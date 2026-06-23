"""User-favorites orchestration handlers.

A `UserFavorite` is a binary M:N edge between a `User` and a `Clinician`.
There is no update verb — favorites are immutable edges — so the audit
discipline is satisfied via direct `record_audit(...)` calls rather than
the `mutate(...)` context manager. Audit rows fire only on actual mutations:
idempotent re-favorites and idempotent un-favorites are silent.

Self-only: all three handlers operate on the requesting user's edges; the
route layer hard-codes the `/users/me/...` path prefix and sources the
user id from the session.
"""

import logging
from uuid import UUID

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.models import Clinician, User, UserFavorite
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework.audit.core import record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import NotFoundError

logger = logging.getLogger(__name__)

_EDGE_AUDIT = FAVORITE_ENTITY.edge_audit


async def handle_add_favorite(
    clinician_id: UUID,
    repo: UserFavoriteRepository,
    clinician_repo: ClinicianRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> UserFavorite:
    """Add a favorite edge from the requesting user to `clinician_id`.

    Idempotent: returns the existing edge unchanged if one already exists.
    Audited only on actual creation. 404 if the clinician does not exist.
    """
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")

    existing = await repo.get_by_pair(
        user_id=requesting_user.id, clinician_id=clinician_id
    )
    if existing is not None:
        return existing

    favorite = await repo.add_favorite(
        user_id=requesting_user.id, clinician_id=clinician_id
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=_EDGE_AUDIT.resource_type,
        resource_id=favorite.id,
        action=_EDGE_AUDIT.action_for("add"),
        before=None,
        after=_EDGE_AUDIT.snapshot(favorite),
    )
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} favorited clinician {clinician_id}"
    )
    return favorite


async def handle_remove_favorite(
    clinician_id: UUID,
    repo: UserFavoriteRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Remove the favorite edge from the requesting user to `clinician_id`.

    Idempotent: no-op if the edge does not exist.
    """
    favorite = await repo.get_by_pair(
        user_id=requesting_user.id, clinician_id=clinician_id
    )
    if favorite is None:
        return

    before = _EDGE_AUDIT.snapshot(favorite)
    favorite_id = favorite.id
    await repo.delete_favorite(favorite)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=_EDGE_AUDIT.resource_type,
        resource_id=favorite_id,
        action=_EDGE_AUDIT.action_for("remove"),
        before=before,
        after=None,
    )
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} unfavorited clinician {clinician_id}"
    )
