"""Repository for :class:`ClinicianAffiliation` sub-resource CRUD.

The framework's generic create / update / delete handlers operate on
the repository via the spec — the framework reads `EntitySpec.repo_dep`
and resolves it via FastAPI. This repository is intentionally a thin
shell over `BaseRepository`: affiliations have no domain-specific
filter, ordering, or join shape that wouldn't be expressed by the
generic create / get-by-id / patch / delete primitives, so the repo
class body is empty.

Register-and-bind at module load via `register_repository` (the
framework's repo-type dispatch reads from that registry — see
`src/framework/persistence/dependencies.py`).
"""

from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ClinicianAffiliationRepository(BaseRepository):
    """Sub-resource of `Clinician` — see module docstring."""


get_clinician_affiliation_repository = register_repository(
    ClinicianAffiliationRepository
)
