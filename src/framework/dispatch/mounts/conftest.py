"""Shared test fixtures for the mounts/ handler tests.

These fixtures are used across test_delete.py, test_create.py,
test_update.py, test_form.py, test_detail.py, and test_list.py.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

from src.framework.audit.core import AuditAction, AuditedResource
from src.framework.dispatch.entity_spec import EntitySpec, RouteSet


def request_stub(query: str = "") -> SimpleNamespace:
    """Minimal SimpleNamespace mimicking the bits of `starlette.Request`
    these handler tests read: `query_params.get(name)` (consumed by
    `parse_page` for pagination) and `url.query` (consumed by
    `base_query` to build pagination links). Tests that don't care
    about pagination pass no query and get the defaults (`page=1`,
    no filter state in the paginator base)."""
    params = dict(parse_qsl(query))
    return SimpleNamespace(
        query_params=SimpleNamespace(get=params.get),
        url=SimpleNamespace(query=query),
    )


@dataclass
class FixtureRow:
    """Stand-in ORM row: just needs `id` plus optional parent FK column.

    `owner_id` defaults to None so tests that don't care about ownership
    can ignore it; the spec's default `owner_attr="owner_id"` reads it
    in `handle_detail`'s `is_self` derivation."""

    id: UUID
    parent_id: UUID | None = None
    owner_id: UUID | None = None
    # Counters so tests can detect commit / delete / audit fired.
    _deleted: bool = False


class FakeSession:
    """Minimal AsyncSession stand-in: tracks commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeAuditRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def record(
        self,
        *,
        actor_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        action: AuditAction,
        before: dict | None = None,
        after: dict | None = None,
    ) -> SimpleNamespace:
        row = {
            "actor_id": actor_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "before": before,
            "after": after,
        }
        self.calls.append(row)
        return SimpleNamespace(**row)


class FakeRepo:
    """Stand-in repo. Wraps an in-memory dict keyed by model class."""

    def __init__(self) -> None:
        self.session = FakeSession()
        self._rows: dict[type, dict[UUID, FixtureRow]] = {}
        self.deleted: list[FixtureRow] = []
        # Optional behavior toggles per test
        self.delete_raises: Exception | None = None

    def _bucket(self, model: type) -> dict[UUID, FixtureRow]:
        return self._rows.setdefault(model, {})

    def seed(self, model: type, row: FixtureRow) -> None:
        self._bucket(model)[row.id] = row

    async def get_by_model_id(
        self, model: type[Any], obj_id: UUID
    ) -> FixtureRow | None:
        return self._bucket(model).get(obj_id)

    async def delete(self, obj: FixtureRow) -> None:
        if self.delete_raises is not None:
            raise self.delete_raises
        obj._deleted = True
        # Remove from any bucket where present.
        for bucket in self._rows.values():
            bucket.pop(obj.id, None)
        self.deleted.append(obj)


class ParentRow:
    """Distinct from FixtureRow so `model is` checks in tests are
    meaningful — `spec.model` and `spec.parent.model` must be different."""

    def __init__(self, id: UUID):
        self.id = id


def make_user(
    *, id_: UUID | None = None, is_superuser: bool = False
) -> SimpleNamespace:
    """User-stub factory that always carries `is_superuser`."""
    return SimpleNamespace(id=id_ or uuid4(), is_superuser=is_superuser)


def make_audit() -> AuditedResource:
    return AuditedResource(
        type="widget",
        snapshot=lambda obj: {"id": str(obj.id)},
        create=AuditAction.CREATE_USER,
        update=AuditAction.UPDATE_USER,
        delete=AuditAction.DELETE_USER,
    )


def top_level_spec(*, write_authz=None, audit=None) -> EntitySpec:
    return EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        write_authz=write_authz,
        audit=audit if audit is not None else make_audit(),
    )


def parent_spec() -> EntitySpec:
    return EntitySpec(
        name="parent",
        url_collection="parents",
        id_param="parent_id",
        model=ParentRow,
        audit=make_audit(),
    )


def child_spec(*, write_authz=None) -> EntitySpec:
    """Owned subentity. Child's FK column is `parent_id`."""
    p = parent_spec()
    return EntitySpec(
        name="widget_part",
        url_collection="widget_parts",
        id_param="part_id",
        model=FixtureRow,
        parent=p,
        write_authz=write_authz,
        audit=make_audit(),
        routes=RouteSet(delete=True),
    )
