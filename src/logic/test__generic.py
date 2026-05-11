"""Framework tests for `src/logic/_generic.py`.

These pin the generic handler behavior against fixture specs and
fixture models — independent of any production entity. The per-entity
spec-correctness suites (`src/api/common/specs/test_<entity>.py`)
already prove each spec declares the right things; the framework
test surface here proves the generic handler does the right work
*given* a well-formed spec.

After phase-2 migration, per-entity delete-route tests are deleted —
this file is the load-bearing assurance that delete behavior is
correct across every migrated entity.
"""

import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic._generic import handle_delete, make_delete_handler
from src.logic.audit import AuditAction, AuditedResource

# --- Fixture model + repo --------------------------------------------------


@dataclass
class _FixtureRow:
    """Stand-in ORM row: just needs `id` plus optional parent FK column."""

    id: UUID
    parent_id: UUID | None = None
    # Counters so tests can detect commit / delete / audit fired.
    _deleted: bool = False


class _FakeSession:
    """Minimal AsyncSession stand-in: tracks commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _FakeAuditRepo:
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


class _FakeRepo:
    """Stand-in repo. Wraps an in-memory dict keyed by model class.

    The framework calls `get_by_model_id(model, id)` and `delete(obj)`;
    the rest is unused.
    """

    def __init__(self) -> None:
        self.session = _FakeSession()
        self._rows: dict[type, dict[UUID, _FixtureRow]] = {}
        self.deleted: list[_FixtureRow] = []
        # Optional behavior toggles per test
        self.delete_raises: Exception | None = None

    def _bucket(self, model: type) -> dict[UUID, _FixtureRow]:
        return self._rows.setdefault(model, {})

    def seed(self, model: type, row: _FixtureRow) -> None:
        self._bucket(model)[row.id] = row

    async def get_by_model_id(
        self, model: type[Any], obj_id: UUID
    ) -> _FixtureRow | None:
        return self._bucket(model).get(obj_id)

    async def delete(self, obj: _FixtureRow) -> None:
        if self.delete_raises is not None:
            raise self.delete_raises
        obj._deleted = True
        # Remove from any bucket where present.
        for bucket in self._rows.values():
            bucket.pop(obj.id, None)
        self.deleted.append(obj)


class _ParentRow:
    """Distinct from _FixtureRow so `model is` checks in tests are
    meaningful — `spec.model` and `spec.parent.model` must be different."""

    def __init__(self, id: UUID):
        self.id = id


# --- Fixture audit + write_authz ------------------------------------------


def _audit() -> AuditedResource:
    return AuditedResource(
        type="widget",
        # Snapshot returns a stub dict; mutate() captures pre/post via
        # this callable.
        snapshot=lambda obj: {"id": str(obj.id)},
        create=AuditAction.CREATE_USER,
        update=AuditAction.UPDATE_USER,
        delete=AuditAction.DELETE_USER,
    )


# --- Spec fixtures --------------------------------------------------------


def _top_level_spec(*, write_authz=None, audit=None) -> EntitySpec:
    return EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        write_authz=write_authz,
        audit=audit if audit is not None else _audit(),
    )


def _parent_spec() -> EntitySpec:
    return EntitySpec(
        name="parent",
        url_collection="parents",
        id_param="parent_id",
        model=_ParentRow,
        audit=_audit(),
    )


def _child_spec(*, write_authz=None) -> EntitySpec:
    """Owned subentity. Child's FK column is `parent_id`
    (matches `f"{parent.name}_id"`)."""
    parent = _parent_spec()
    return EntitySpec(
        name="widget_part",
        url_collection="widget_parts",
        id_param="part_id",
        model=_FixtureRow,
        parent=parent,
        write_authz=write_authz,
        audit=_audit(),
        # Subentity needs at least one route opted in to satisfy the
        # construction-time validation introduced in A2.
        routes=RouteSet(delete=True),
    )


# --- Happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_top_level_delete_happy_path():
    """Standard delete with no auth predicate: target loaded, deleted,
    audit row written, commit fired."""
    spec = _top_level_spec(write_authz=None)
    repo = _FakeRepo()
    audit_repo = _FakeAuditRepo()
    user = SimpleNamespace(id=uuid4())
    target_id = uuid4()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert len(repo.deleted) == 1
    assert repo.deleted[0].id == target_id
    assert repo.session.commits == 1
    assert len(audit_repo.calls) == 1
    call = audit_repo.calls[0]
    assert call["resource_type"] == "widget"
    assert call["action"] == AuditAction.DELETE_USER
    assert call["actor_id"] == user.id


@pytest.mark.asyncio
async def test_top_level_delete_invokes_write_authz_against_target():
    """`write_authz` is called against the target with action text."""
    calls = []

    def authz(obj, user, *, action):
        calls.append((obj, user, action))

    spec = _top_level_spec(write_authz=authz)
    repo = _FakeRepo()
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo.seed(_FixtureRow, target)
    user = SimpleNamespace(id=uuid4())

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=user,
    )

    assert len(calls) == 1
    assert calls[0][0] is target
    assert calls[0][1] is user
    assert "delete this widget" in calls[0][2]


@pytest.mark.asyncio
async def test_subentity_delete_happy_path():
    """Owned-subentity: parent-FK verified; write_authz runs against
    parent; child deleted + audit row written for child."""
    child_spec = _child_spec()
    parent_spec = child_spec.parent
    repo = _FakeRepo()
    parent_id = uuid4()
    child_id = uuid4()
    repo.seed(parent_spec.model, _ParentRow(id=parent_id))
    repo.seed(child_spec.model, _FixtureRow(id=child_id, parent_id=parent_id))
    audit_repo = _FakeAuditRepo()
    user = SimpleNamespace(id=uuid4())

    await handle_delete(
        child_spec,
        target_id=child_id,
        parent_id=parent_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert len(repo.deleted) == 1
    assert repo.deleted[0].id == child_id
    assert audit_repo.calls[0]["resource_type"] == "widget"  # from child audit


@pytest.mark.asyncio
async def test_subentity_write_authz_runs_against_parent():
    """Auth follows the ownership chain: the predicate sees the parent,
    not the child."""
    seen = []

    def authz(obj, user, *, action):
        seen.append(obj)

    child_spec = _child_spec(write_authz=authz)
    parent_id = uuid4()
    child_id = uuid4()
    parent = _ParentRow(id=parent_id)
    child = _FixtureRow(id=child_id, parent_id=parent_id)
    repo = _FakeRepo()
    repo.seed(child_spec.parent.model, parent)
    repo.seed(child_spec.model, child)

    await handle_delete(
        child_spec,
        target_id=child_id,
        parent_id=parent_id,
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert len(seen) == 1
    assert seen[0] is parent  # against parent, not child


# --- Error paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_target_not_found_raises_not_found():
    spec = _top_level_spec()
    repo = _FakeRepo()  # empty
    with pytest.raises(NotFoundError):
        await handle_delete(
            spec,
            target_id=uuid4(),
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )
    assert repo.deleted == []


@pytest.mark.asyncio
async def test_subentity_parent_fk_mismatch_raises_not_found():
    """Child exists but belongs to a different parent — 404, never a hint
    that the child is real but elsewhere."""
    child_spec = _child_spec()
    parent_id = uuid4()
    other_parent_id = uuid4()
    child_id = uuid4()
    repo = _FakeRepo()
    repo.seed(child_spec.parent.model, _ParentRow(id=parent_id))
    repo.seed(child_spec.parent.model, _ParentRow(id=other_parent_id))
    repo.seed(child_spec.model, _FixtureRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_delete(
            child_spec,
            target_id=child_id,
            parent_id=other_parent_id,  # different parent
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_subentity_parent_not_found_raises_not_found():
    child_spec = _child_spec()
    parent_id = uuid4()
    child_id = uuid4()
    repo = _FakeRepo()
    # Child seeded but parent not seeded.
    repo.seed(child_spec.model, _FixtureRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_delete(
            child_spec,
            target_id=child_id,
            parent_id=parent_id,
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_subentity_without_parent_id_raises_value_error():
    """Spec has parent but caller didn't supply parent_id — programming
    error, fail loudly."""
    child_spec = _child_spec()
    child_id = uuid4()
    repo = _FakeRepo()
    repo.seed(child_spec.model, _FixtureRow(id=child_id))

    with pytest.raises(ValueError, match="parent"):
        await handle_delete(
            child_spec,
            target_id=child_id,
            parent_id=None,
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_write_authz_raises_propagates_no_audit_no_commit():
    """If the predicate raises, no audit row + no commit — the
    transaction rolls back atomically."""

    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    spec = _top_level_spec(write_authz=authz)
    repo = _FakeRepo()
    target_id = uuid4()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))
    audit_repo = _FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )

    assert repo.deleted == []
    assert audit_repo.calls == []
    assert repo.session.commits == 0


@pytest.mark.asyncio
async def test_delete_raises_propagates_no_audit_no_commit():
    """Repo's delete blowing up means `mutate(...)` exits via the
    exception path: no audit row, no commit."""
    spec = _top_level_spec()
    repo = _FakeRepo()
    target_id = uuid4()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))
    repo.delete_raises = RuntimeError("db blew up")
    audit_repo = _FakeAuditRepo()

    with pytest.raises(RuntimeError, match="db blew up"):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )

    assert audit_repo.calls == []
    assert repo.session.commits == 0


@pytest.mark.asyncio
async def test_no_audit_binding_raises_value_error():
    """Phase 2 framework refuses to silently skip the audit row."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=None,  # missing audit
    )
    repo = _FakeRepo()
    target_id = uuid4()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    with pytest.raises(ValueError, match="audit"):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_no_write_authz_skips_auth_check():
    """Top-level entity with `write_authz=None` proceeds without an
    auth check — the route layer's `write_user_dep` is the only gate.
    (Pinned so a future refactor doesn't quietly add a default
    predicate.)"""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert len(repo.deleted) == 1


# --- make_delete_handler factory ------------------------------------------


def test_make_delete_handler_top_level_signature():
    """Returned handler exposes the spec's id_param + repo/audit/user."""
    spec = _top_level_spec()
    handler = make_delete_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "widget_id",
        "repo",
        "audit_repo",
        "requesting_user",
    }


def test_make_delete_handler_subentity_includes_parent_id():
    """Subentity handler exposes both id_param and parent id_param."""
    spec = _child_spec()
    handler = make_delete_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "part_id",
        "parent_id",
        "repo",
        "audit_repo",
        "requesting_user",
    }


def test_make_delete_handler_name_includes_entity():
    """Stack traces should be readable — handler `__name__` includes
    the entity name."""
    spec = _top_level_spec()
    handler = make_delete_handler(spec)
    assert handler.__name__ == "_handle_delete_widget"
