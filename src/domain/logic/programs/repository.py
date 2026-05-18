"""Repository for the `Program` entity.

Minimal — no custom queries today. ``BaseRepository`` supplies the
generic list / get / create / patch / delete operations the framework's
mount layer calls. The hook is here so adding a per-Program custom
query later (e.g. ``list_for_org``) doesn't require restructuring.
"""

from src.framework.persistence.base_repository import BaseRepository


class ProgramRepository(BaseRepository):
    pass
