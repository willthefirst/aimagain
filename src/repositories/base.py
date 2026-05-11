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

from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")
M = TypeVar("M")


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_by_id(self, model: type[M], obj_id: UUID) -> M | None:
        """Fetch a single row by primary key. Returns `None` if missing.

        Generic over the model class: `_get_by_id(User, id)` returns
        `User | None`, verified by the type checker via `M`.
        """
        stmt = select(model).filter(model.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _list(
        self,
        stmt: Select[tuple[T]],
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[T]:
        """Execute a `select(...)` statement and return its scalars.

        Generic over the selected entity: `_list(select(Post))` returns
        `Sequence[Post]`, verified by the type checker via `T`. Centralizes
        the `result = await session.execute(stmt); return
        result.scalars().all()` boilerplate every list-style method repeats.

        `limit` and `offset` are optional kwargs — when both are `None`,
        returns the full result set unchanged. Filter, order, and join
        logic stay in the calling method (where the domain-specific shape
        is most expressive).
        """
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _count(self, stmt: Select[Any]) -> int:
        """Count rows matching `stmt` without fetching them.

        Wraps `select(func.count()).select_from(stmt.subquery())` so the
        caller passes the same `select(...)` they'd pass to `_list`. The
        subquery wrapper preserves filters, joins, and `.distinct()` — the
        count reflects exactly the rows `_list` would return ignoring
        pagination.
        """
        count_stmt = select(func.count()).select_from(stmt.subquery())
        result = await self.session.execute(count_stmt)
        return result.scalar_one()

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

    # --- Public framework-facing primitives ----------------------------
    # The protected primitives above are intended for intra-cluster
    # repository methods. Cross-cluster framework code (the generic
    # handlers in `src/logic/_generic.py`) reaches in via the public
    # aliases below — same behavior, the underscore convention stays
    # intact for intra-cluster usage.

    async def get_by_model_id(self, model: type[M], obj_id: UUID) -> M | None:
        """Public alias for `_get_by_id`. Used by generic framework
        handlers and per-entity call sites that need a typed fetch by
        primary key — `get_by_model_id(User, id)` returns `User | None`.
        """
        return await self._get_by_id(model, obj_id)

    async def delete(self, obj: Any) -> None:
        """Public alias for `_delete`. Used by generic framework
        handlers (e.g. `handle_delete`)."""
        await self._delete(obj)

    async def create(self, obj: Any) -> Any:
        """Public alias for `_persist_new`. Used by `handle_create`."""
        return await self._persist_new(obj)

    async def add_child(self, parent: Any, collection: str, child: Any) -> Any:
        """Public alias for `_add_child`. Used by `handle_create` on
        owned subentities — appends `child` to
        `parent.<collection>` so the parent's in-memory state stays
        coherent for the post-mutation audit snapshot."""
        return await self._add_child(parent, collection, child)

    async def patch(self, obj: Any, **fields: Any) -> Any:
        """Public alias for `_patch`. Used by `handle_update` — applies
        non-`None` fields, flushes, refreshes."""
        return await self._patch(obj, **fields)

    async def create_polymorphic(
        self, parent: Any, detail: Any, *, detail_relationship: str
    ) -> Any:
        """Persist a polymorphic parent + its per-kind detail row in one
        flush. Lifts the post-repo's `_attach_detail` flow into the
        base so any polymorphic entity gets it for free; the
        kind-to-relationship binding lives on the entity's
        `DiscriminatorRegistry` (`spec.discriminator[kind].detail_relationship`).
        """
        setattr(parent, detail_relationship, detail)
        return await self._persist_new(parent)
