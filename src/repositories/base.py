"""Common session management + CRUD primitives shared by every repository.

The four protected primitives (`_get_by_id`, `_persist_new`, `_add_child`,
`_patch`, `_delete`) capture the exact shapes that every resource repo was
writing by hand. They own only the flush/refresh ritual; they never call
`commit()` — the logic layer owns the transaction boundary.

When to delegate vs. write the method out: if your repo method body is one
of these shapes plus *zero* other operations (no joins, no filters, no
custom ordering, no per-kind dispatch), delegate. Otherwise write the
method body explicitly — that domain-specific shape is exactly what the
named per-resource methods are for.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_by_id(self, model: type[Any], obj_id: UUID) -> Any | None:
        """Fetch a single row by primary key. Returns `None` if missing."""
        stmt = select(model).filter(model.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _persist_new(self, obj: Any) -> Any:
        """Add a fresh ORM instance, flush, and refresh; return the row.

        For rows that belong in a parent's loaded collection, use
        `_add_child` instead so the parent's in-memory state stays
        coherent for callers that snapshot the parent right after the
        mutation.
        """
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def _add_child(self, parent: Any, collection: str, child: Any) -> Any:
        """Append `child` to `parent.<collection>`, flush, and refresh.

        Going through the relationship attribute (rather than just
        setting `child.<fk> = parent.id`) keeps the parent's loaded
        collection consistent — callers snapshotting the parent see the
        new child without a second `session.refresh(parent, ...)`.
        """
        getattr(parent, collection).append(child)
        await self.session.flush()
        await self.session.refresh(child)
        return child

    async def _patch(self, obj: Any, **fields: Any) -> Any:
        """Apply non-`None` `fields` to `obj`, flush, and refresh.

        `None` values are skipped so callers can pass
        `payload.model_dump(exclude_unset=True)` directly. Use a custom
        method body when you need a richer skip predicate (e.g. only
        fields belonging to a particular kind).
        """
        for field_name, value in fields.items():
            if value is None:
                continue
            setattr(obj, field_name, value)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def _delete(self, obj: Any) -> None:
        """Hard-delete the row; flush. Cascades fire per the model's
        SQLAlchemy and FK configuration."""
        await self.session.delete(obj)
        await self.session.flush()
