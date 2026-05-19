"""Repository for the `Program` entity.

Mostly delegates to ``BaseRepository`` for the generic CRUD path the
framework's mount layer calls. The one custom read — ``list_for_user``
— mirrors :meth:`OrganizationRepository.list_for_user` /
:meth:`ProviderRepository.list_for_user` so the same per-user scoping
pattern works on the ``intake`` post form.
"""

import uuid
from typing import Sequence

from sqlalchemy import select

from src.domain.models import Program
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ProgramRepository(BaseRepository):
    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Program]:
        """Lists every Program owned by ``user_id``, newest first.

        Mirrors :meth:`OrganizationRepository.list_for_user` and
        :meth:`ProviderRepository.list_for_user`. Drives the
        ``intake`` post create/edit form's Program-picker
        dropdown and pairs with the wire-level ownership check in
        ``POST_ENTITY.payload_authz_path``."""
        stmt = (
            select(Program)
            .filter(Program.owner_id == user_id)
            .order_by(Program.created_at.desc())
        )
        return await self._list(stmt)


get_program_repository = register_repository(ProgramRepository)
