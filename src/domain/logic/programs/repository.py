"""Repository for the `Program` entity.

Delegates to ``BaseRepository`` for the generic CRUD path the
framework's mount layer calls. ``list_for_user`` is a domain-named
entry point onto the framework's ``list_owned_by`` helper — same
"owned rows newest first" shape Organization and Clinician use.
"""

import uuid
from typing import Sequence

from src.domain.models import Program
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ProgramRepository(BaseRepository):
    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Program]:
        """Lists every Program owned by ``user_id``, newest first.
        Drives the ``intake`` post create/edit form's Program-picker
        dropdown and pairs with the wire-level ownership check in
        ``POST_ENTITY.payload_authz_path``."""
        return await self.list_owned_by(Program, user_id)


get_program_repository = register_repository(ProgramRepository)
