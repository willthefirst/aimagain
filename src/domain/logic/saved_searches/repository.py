"""Repository for :class:`SavedSearch` sub-resource CRUD.

Thin shell over `BaseRepository`: the create / patch / delete
primitives the framework's generic handlers call are inherited as-is,
and the owner-scoped listing reuses ``BaseRepository.list_owned_by``
(the bespoke list handler calls it directly with
``owner_attr="user_id"``). No domain-specific query shape lives here,
so the class body is empty.

Register-and-bind at module load via `register_repository` (the
framework's repo-type dispatch reads from that registry — see
`src/framework/persistence/dependencies.py`).
"""

from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class SavedSearchRepository(BaseRepository):
    """Sub-resource of `User` — see module docstring."""


get_saved_search_repository = register_repository(SavedSearchRepository)
