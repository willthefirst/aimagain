"""Repository for :class:`ClinicianAffiliation` sub-resource CRUD.

The framework's generic create / update / delete handlers operate on
the repository via the spec — the framework reads `EntitySpec.repo_dep`
and resolves it via FastAPI. This repository is intentionally a thin
shell over `BaseRepository`: affiliations have no domain-specific
filter, ordering, or join shape that wouldn't be expressed by the
generic create / get-by-id / patch / delete primitives. The one
bespoke read is `list_org_members` — the org-side door onto the same
join (#1524).

Register-and-bind at module load via `register_repository` (the
framework's repo-type dispatch reads from that registry — see
`src/framework/persistence/dependencies.py`).
"""

import uuid
from typing import Sequence

from sqlalchemy import select

from src.domain.models import ClinicianAffiliation
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ClinicianAffiliationRepository(BaseRepository):
    """Sub-resource of `Clinician` — see module docstring.

    The "one join, two doors" surface (#1524): the same `(clinician × org)`
    join that the clinician edit page lists by `clinician_id` is listed
    here by `org_id` to power the org's Members list
    (`GET /organizations/{id}/members`). The mutation door stays on the
    clinician side — the affiliation is FK-owned by the clinician, so
    add/edit/remove route through `/clinicians/{id}/clinician_affiliations`.
    """

    async def list_org_members(
        self, org_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> Sequence[ClinicianAffiliation]:
        """List the affiliations whose `org_id` is this organization,
        newest first. Each row's `clinician` and `org` relations are
        `selectin`-loaded on the model, so the template reads
        `aff.clinician.<name>` without a per-row query."""
        stmt = (
            select(ClinicianAffiliation)
            .filter(ClinicianAffiliation.org_id == org_id)
            .order_by(ClinicianAffiliation.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)


get_clinician_affiliation_repository = register_repository(
    ClinicianAffiliationRepository
)
