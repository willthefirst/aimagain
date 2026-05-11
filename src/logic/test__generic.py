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


# --- handle_create framework tests ---------------------------------------


from dataclasses import dataclass as _dc
from typing import Any as _Any

from pydantic import BaseModel as _BaseModel

from src.api.common.entity_spec import RelatedListSubresource  # noqa: F401
from src.logic._generic import handle_create, make_create_handler
from src.models._polymorphic import DiscriminatorRegistry


class _AnyRow:
    """Flexible fixture row used by create tests — accepts any kwargs."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, "id"):
            self.id = uuid4()


def _create_fake_repo() -> _FakeRepo:
    """Returns a `_FakeRepo` extended with `create` / `add_child` /
    `create_polymorphic` for the new framework path."""
    repo = _FakeRepo()
    created_rows: list[_Any] = []
    added_children: list[tuple[_Any, str, _Any]] = []
    created_polymorphic: list[tuple[_Any, _Any, str]] = []
    repo.created_rows = created_rows  # type: ignore[attr-defined]
    repo.added_children = added_children  # type: ignore[attr-defined]
    repo.created_polymorphic = created_polymorphic  # type: ignore[attr-defined]

    async def create(obj):
        if not hasattr(obj, "id"):
            obj.id = uuid4()
        created_rows.append(obj)
        return obj

    async def add_child(parent, collection, child):
        if not hasattr(child, "id"):
            child.id = uuid4()
        added_children.append((parent, collection, child))
        # Mimic the real method: append to parent's collection so
        # snapshots see it.
        bucket = getattr(parent, collection, None)
        if bucket is None:
            bucket = []
            setattr(parent, collection, bucket)
        bucket.append(child)
        return child

    async def create_polymorphic(parent, detail, *, detail_relationship):
        if not hasattr(parent, "id"):
            parent.id = uuid4()
        setattr(parent, detail_relationship, detail)
        created_polymorphic.append((parent, detail, detail_relationship))
        return parent

    repo.create = create  # type: ignore[assignment]
    repo.add_child = add_child  # type: ignore[assignment]
    repo.create_polymorphic = create_polymorphic  # type: ignore[assignment]
    return repo


class _StandardPayload(_BaseModel):
    practice_name: str = "Acme"
    location_city: str = "NYC"


@pytest.mark.asyncio
async def test_create_top_level_persists_and_audits():
    """Standard create: instance built from payload + owner column set,
    persisted, audit row written."""
    audit_used = _audit()
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=audit_used,
    )
    repo = _create_fake_repo()
    audit_repo = _FakeAuditRepo()
    user = SimpleNamespace(id=uuid4())

    created = await handle_create(
        spec,
        payload=_StandardPayload(practice_name="P", location_city="C"),
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert created.practice_name == "P"
    assert created.location_city == "C"
    assert created.owner_id == user.id
    assert len(repo.created_rows) == 1
    assert len(audit_repo.calls) == 1
    assert audit_repo.calls[0]["action"] == audit_used.create


@pytest.mark.asyncio
async def test_create_top_level_without_owner_attr():
    """When `owner_attr=None` (e.g. users — resource IS the user) the
    framework doesn't try to set an owner column."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        owner_attr=None,
        audit=_audit(),
    )
    repo = _create_fake_repo()
    user = SimpleNamespace(id=uuid4())

    created = await handle_create(
        spec,
        payload=_StandardPayload(),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=user,
    )

    # Owner column never assigned (would have been "owner_id" by default).
    assert not hasattr(created, "owner_id")


@pytest.mark.asyncio
async def test_create_subentity_appended_to_parent_and_audited():
    """Owned-subentity create: parent loaded, write_authz on parent,
    child instantiated + appended via `add_child`, audit on child."""
    seen_authz = []

    def authz(obj, user, *, action):
        seen_authz.append((obj, action))

    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        write_authz=authz,
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()
    parent_id = uuid4()
    parent_obj = _ParentRow(id=parent_id)
    repo.seed(parent_spec.model, parent_obj)
    audit_repo = _FakeAuditRepo()
    user = SimpleNamespace(id=uuid4())

    created = await handle_create(
        spec,
        payload=_StandardPayload(),
        parent_id=parent_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert len(seen_authz) == 1
    assert seen_authz[0][0] is parent_obj  # against parent
    assert len(repo.added_children) == 1
    assert repo.added_children[0][0] is parent_obj
    assert repo.added_children[0][1] == "parts"  # collection = url_collection
    assert repo.added_children[0][2] is created
    assert len(audit_repo.calls) == 1


@pytest.mark.asyncio
async def test_create_subentity_parent_not_found():
    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()  # empty
    with pytest.raises(NotFoundError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=uuid4(),
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_create_subentity_missing_parent_id_raises():
    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    with pytest.raises(ValueError, match="parent"):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=None,
            repo=_create_fake_repo(),
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


# --- Polymorphic create --------------------------------------------------


@_dc(frozen=True)
class _FixtureKindSpec:
    """Stands in for `PostKindSpec` — just the framework-required attrs."""

    kind: str
    detail_model: type
    detail_fields: tuple[str, ...]
    detail_relationship: str


class _RedKindPayload(_BaseModel):
    kind: str
    redness: int = 0


class _BlueKindPayload(_BaseModel):
    kind: str
    blueness: int = 0


class _RedDetail:
    def __init__(self, redness: int = 0):
        self.redness = redness


class _BlueDetail:
    def __init__(self, blueness: int = 0):
        self.blueness = blueness


@pytest.mark.asyncio
async def test_create_polymorphic_dispatches_via_discriminator():
    """The payload's `kind` picks the kind_spec; parent has the
    discriminator column set; detail built from kind_spec.detail_fields."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureKindSpec(
                kind="red",
                detail_model=_RedDetail,
                detail_fields=("redness",),
                detail_relationship="red_detail",
            ),
            "blue": _FixtureKindSpec(
                kind="blue",
                detail_model=_BlueDetail,
                detail_fields=("blueness",),
                detail_relationship="blue_detail",
            ),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_AnyRow,
        audit=_audit(),
        discriminator=registry,
    )
    repo = _create_fake_repo()
    user = SimpleNamespace(id=uuid4())

    created_red = await handle_create(
        spec,
        payload=_RedKindPayload(kind="red", redness=7),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=user,
    )

    # Parent has discriminator column set + owner.
    assert created_red.kind == "red"
    assert created_red.owner_id == user.id
    # Detail attached at the kind_spec.detail_relationship.
    assert isinstance(created_red.red_detail, _RedDetail)
    assert created_red.red_detail.redness == 7
    assert len(repo.created_polymorphic) == 1

    # And the other kind goes through the same path.
    created_blue = await handle_create(
        spec,
        payload=_BlueKindPayload(kind="blue", blueness=11),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=user,
    )
    assert created_blue.kind == "blue"
    assert created_blue.blue_detail.blueness == 11


# --- Error / edge cases --------------------------------------------------


@pytest.mark.asyncio
async def test_create_no_audit_binding_raises():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=None,
    )
    with pytest.raises(ValueError, match="audit"):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            repo=_create_fake_repo(),
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_create_subentity_write_authz_raises_rolls_back():
    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        write_authz=authz,
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()
    parent_id = uuid4()
    repo.seed(parent_spec.model, _ParentRow(id=parent_id))
    audit_repo = _FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=parent_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )

    # Nothing added, no audit, no commit.
    assert repo.added_children == []
    assert audit_repo.calls == []
    assert repo.session.commits == 0


# --- make_create_handler factory ------------------------------------------


def test_make_create_handler_top_level_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    handler = make_create_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "payload",
        "repo",
        "audit_repo",
        "requesting_user",
    }


def test_make_create_handler_subentity_includes_parent_id():
    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    handler = make_create_handler(spec)
    sig = inspect.signature(handler)
    assert "parent_id" in sig.parameters
    assert "payload" in sig.parameters


def test_make_create_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    handler = make_create_handler(spec)
    assert handler.__name__ == "_handle_create_widget"


# --- handle_update framework tests ---------------------------------------


from src.api.common.exceptions import BadRequestError  # noqa: E402
from src.logic._generic import handle_update, make_update_handler  # noqa: E402


def _update_fake_repo() -> _FakeRepo:
    """`_FakeRepo` extended with `patch` for the framework's update path."""
    repo = _create_fake_repo()  # already has create / add_child / create_polymorphic
    patched: list[tuple[_Any, dict]] = []
    repo.patched = patched  # type: ignore[attr-defined]

    async def patch(obj, **fields):
        applied = {}
        for k, v in fields.items():
            if v is None:
                continue
            setattr(obj, k, v)
            applied[k] = v
        patched.append((obj, applied))
        return obj

    repo.patch = patch  # type: ignore[assignment]
    return repo


class _UpdatePayload(_BaseModel):
    practice_name: str | None = None
    location_city: str | None = None


@pytest.mark.asyncio
async def test_update_top_level_partial_patch_via_exclude_unset():
    """`exclude_unset` — only explicitly-set fields are patched."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    target = _AnyRow(id=target_id, practice_name="Old", location_city="OldCity")
    repo.seed(_AnyRow, target)
    audit_repo = _FakeAuditRepo()

    await handle_update(
        spec,
        target_id=target_id,
        payload=_UpdatePayload(practice_name="New"),  # location_city unset
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert target.practice_name == "New"
    assert target.location_city == "OldCity"  # unchanged
    assert len(audit_repo.calls) == 1
    # Verify only one field made it into the patch dict.
    patched_obj, applied = repo.patched[0]
    assert patched_obj is target
    assert applied == {"practice_name": "New"}


@pytest.mark.asyncio
async def test_update_invokes_write_authz_against_target():
    seen = []

    def authz(obj, user, *, action):
        seen.append((obj, action))

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        write_authz=authz,
        audit=_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    target = _AnyRow(id=target_id)
    repo.seed(_AnyRow, target)

    await handle_update(
        spec,
        target_id=target_id,
        payload=_UpdatePayload(),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert len(seen) == 1
    assert seen[0][0] is target
    assert "update this widget" in seen[0][1]


@pytest.mark.asyncio
async def test_update_subentity_happy_path():
    """Subentity: parent loaded, FK matched, write_authz on parent, detail patched."""
    seen_authz = []

    def authz(obj, user, *, action):
        seen_authz.append(obj)

    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        write_authz=authz,
        routes=RouteSet(update=True),
        update_adapter=__import__("pydantic").TypeAdapter(_UpdatePayload),
    )
    repo = _update_fake_repo()
    parent_id = uuid4()
    parent_obj = _ParentRow(id=parent_id)
    repo.seed(parent_spec.model, parent_obj)
    child_id = uuid4()
    child = _AnyRow(id=child_id, parent_id=parent_id, practice_name="Old")
    repo.seed(_AnyRow, child)

    await handle_update(
        spec,
        target_id=child_id,
        parent_id=parent_id,
        payload=_UpdatePayload(practice_name="New"),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert seen_authz == [parent_obj]
    assert child.practice_name == "New"


@pytest.mark.asyncio
async def test_update_subentity_parent_fk_mismatch_404():
    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        routes=RouteSet(update=True),
        update_adapter=__import__("pydantic").TypeAdapter(_UpdatePayload),
    )
    repo = _update_fake_repo()
    parent_id = uuid4()
    other_parent_id = uuid4()
    child_id = uuid4()
    repo.seed(parent_spec.model, _ParentRow(id=parent_id))
    repo.seed(parent_spec.model, _ParentRow(id=other_parent_id))
    repo.seed(_AnyRow, _AnyRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_update(
            spec,
            target_id=child_id,
            parent_id=other_parent_id,
            payload=_UpdatePayload(),
            repo=repo,
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


# --- Polymorphic update --------------------------------------------------


class _RedUpdatePayload(_BaseModel):
    kind: str
    redness: int | None = None


class _BlueUpdatePayload(_BaseModel):
    kind: str
    blueness: int | None = None


@pytest.mark.asyncio
async def test_update_polymorphic_patches_detail_row():
    """Payload kind matches target kind; detail row patched, parent not."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureKindSpec(
                kind="red",
                detail_model=_RedDetail,
                detail_fields=("redness",),
                detail_relationship="red_detail",
            ),
            "blue": _FixtureKindSpec(
                kind="blue",
                detail_model=_BlueDetail,
                detail_fields=("blueness",),
                detail_relationship="blue_detail",
            ),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_AnyRow,
        audit=_audit(),
        discriminator=registry,
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    detail = _RedDetail(redness=3)
    target = _AnyRow(id=target_id, kind="red", red_detail=detail)
    repo.seed(_AnyRow, target)

    await handle_update(
        spec,
        target_id=target_id,
        payload=_RedUpdatePayload(kind="red", redness=99),
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert detail.redness == 99


@pytest.mark.asyncio
async def test_update_polymorphic_kind_mismatch_raises_bad_request():
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureKindSpec(
                kind="red",
                detail_model=_RedDetail,
                detail_fields=("redness",),
                detail_relationship="red_detail",
            ),
            "blue": _FixtureKindSpec(
                kind="blue",
                detail_model=_BlueDetail,
                detail_fields=("blueness",),
                detail_relationship="blue_detail",
            ),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_AnyRow,
        audit=_audit(),
        discriminator=registry,
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    target = _AnyRow(id=target_id, kind="red", red_detail=_RedDetail())
    repo.seed(_AnyRow, target)
    audit_repo = _FakeAuditRepo()

    with pytest.raises(BadRequestError):
        await handle_update(
            spec,
            target_id=target_id,
            payload=_BlueUpdatePayload(kind="blue", blueness=5),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )

    # No audit, no commit on the kind-mismatch path.
    assert audit_repo.calls == []
    assert repo.session.commits == 0


# --- Error / edge cases --------------------------------------------------


@pytest.mark.asyncio
async def test_update_target_not_found():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    with pytest.raises(NotFoundError):
        await handle_update(
            spec,
            target_id=uuid4(),
            payload=_UpdatePayload(),
            repo=_update_fake_repo(),
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_update_write_authz_raises_no_audit_no_commit():
    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        write_authz=authz,
        audit=_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    repo.seed(_AnyRow, _AnyRow(id=target_id))
    audit_repo = _FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_update(
            spec,
            target_id=target_id,
            payload=_UpdatePayload(),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )

    assert repo.patched == []
    assert audit_repo.calls == []
    assert repo.session.commits == 0


@pytest.mark.asyncio
async def test_update_no_audit_binding_raises():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=None,
    )
    with pytest.raises(ValueError, match="audit"):
        await handle_update(
            spec,
            target_id=uuid4(),
            payload=_UpdatePayload(),
            repo=_update_fake_repo(),
            audit_repo=_FakeAuditRepo(),
            requesting_user=SimpleNamespace(id=uuid4()),
        )


# --- make_update_handler factory ------------------------------------------


def test_make_update_handler_top_level_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    handler = make_update_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "widget_id",
        "payload",
        "repo",
        "audit_repo",
        "requesting_user",
    }


def test_make_update_handler_subentity_includes_parent_id():
    parent_spec = _parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=parent_spec,
        audit=_audit(),
        routes=RouteSet(update=True),
        update_adapter=__import__("pydantic").TypeAdapter(_UpdatePayload),
    )
    handler = make_update_handler(spec)
    sig = inspect.signature(handler)
    assert "parent_id" in sig.parameters
    assert "part_id" in sig.parameters


def test_make_update_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=_audit(),
    )
    handler = make_update_handler(spec)
    assert handler.__name__ == "_handle_update_widget"


# --- handle_get_edit_form framework tests --------------------------------


from src.logic._generic import (  # noqa: E402
    handle_get_edit_form,
    make_edit_form_handler,
)


@_dc(frozen=True)
class _FixtureEditKindSpec:
    """Stands in for `PostKindSpec` — only the `edit_template` attr is
    load-bearing for the edit-form path."""

    edit_template: str


class _PolyRow:
    """Stand-in polymorphic parent: has an `id` and a `kind` column."""

    def __init__(self, id: UUID, kind: str):
        self.id = id
        self.kind = kind


@pytest.mark.asyncio
async def test_edit_form_top_level_happy_path():
    """Load target, no write_authz, returns context with entity under
    `spec.name`. No `template_name` for non-polymorphic entities."""
    spec = _top_level_spec(write_authz=None)
    repo = _FakeRepo()
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo.seed(_FixtureRow, target)
    user = SimpleNamespace(id=uuid4())
    request = SimpleNamespace()

    context = await handle_get_edit_form(
        spec,
        request=request,
        target_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert context["request"] is request
    assert context["widget"] is target  # bound under spec.name
    assert context["current_user"] is user
    assert "template_name" not in context


@pytest.mark.asyncio
async def test_edit_form_invokes_write_authz_against_target():
    """`write_authz` is called against the target with action text."""
    calls = []

    def authz(obj, user, *, action):
        calls.append((obj, user, action))

    spec = _top_level_spec(write_authz=authz)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)
    user = SimpleNamespace(id=uuid4())

    await handle_get_edit_form(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert len(calls) == 1
    assert calls[0][0] is target
    assert calls[0][1] is user
    assert "edit this widget" in calls[0][2]


@pytest.mark.asyncio
async def test_edit_form_target_not_found_raises_not_found():
    spec = _top_level_spec()
    repo = _FakeRepo()
    with pytest.raises(NotFoundError):
        await handle_get_edit_form(
            spec,
            request=SimpleNamespace(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_edit_form_write_authz_raises_propagates():
    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    spec = _top_level_spec(write_authz=authz)
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))
    with pytest.raises(ForbiddenError):
        await handle_get_edit_form(
            spec,
            request=SimpleNamespace(),
            target_id=target_id,
            repo=repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_edit_form_polymorphic_returns_kind_template():
    """For polymorphic entities, the context carries `template_name`
    derived from the discriminator-registry entry's `edit_template`."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureEditKindSpec(edit_template="paintings/edit_red.html"),
            "blue": _FixtureEditKindSpec(edit_template="paintings/edit_blue.html"),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=_audit(),
        discriminator=registry,
    )
    target_id = uuid4()
    target = _PolyRow(id=target_id, kind="blue")
    repo = _FakeRepo()
    repo.seed(_PolyRow, target)

    context = await handle_get_edit_form(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4()),
    )

    assert context["painting"] is target
    assert context["template_name"] == "paintings/edit_blue.html"


# --- make_edit_form_handler factory ---------------------------------------


def test_make_edit_form_handler_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
    )
    handler = make_edit_form_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {"request", "widget_id", "repo", "requesting_user"}


def test_make_edit_form_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
    )
    handler = make_edit_form_handler(spec)
    assert handler.__name__ == "_handle_get_widget_edit_form"


@pytest.mark.asyncio
async def test_make_edit_form_handler_delegates_to_handle_get_edit_form():
    """The factory-built handler invokes `handle_get_edit_form` with the
    spec bound and the URL/dep-resolved kwargs forwarded."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)
    user = SimpleNamespace(id=uuid4())
    request = SimpleNamespace()

    handler = make_edit_form_handler(spec)
    context = await handler(
        request=request,
        widget_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert context["widget"] is target
    assert context["current_user"] is user


# --- handle_detail framework tests ---------------------------------------


from src.logic._generic import handle_detail, make_detail_handler  # noqa: E402


def _can_edit_for_owner(obj, user) -> bool:
    """Stand-in for `is_owner_or_admin` — predicate form of write_authz."""
    return user is not None and getattr(obj, "owner_id", None) == user.id


@pytest.mark.asyncio
async def test_detail_top_level_happy_path():
    """No can_write, no extras: load target, bind under spec.name."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)
    user = SimpleNamespace(id=uuid4())

    context = await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert context["widget"] is target
    assert context["current_user"] is user
    assert "can_edit" not in context  # no can_write declared


@pytest.mark.asyncio
async def test_detail_populates_can_edit_from_can_write():
    """When `spec.can_write` is set, `can_edit` is populated by calling it."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        can_write=_can_edit_for_owner,
        audit=_audit(),
    )
    target_id = uuid4()
    owner_id = uuid4()
    owner = SimpleNamespace(id=owner_id)
    stranger = SimpleNamespace(id=uuid4())

    # _FixtureRow doesn't have owner_id; simulate by setattr.
    target = _FixtureRow(id=target_id)
    target.owner_id = owner_id  # type: ignore[attr-defined]
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    owner_ctx = await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=owner,
    )
    assert owner_ctx["can_edit"] is True

    stranger_ctx = await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=stranger,
    )
    assert stranger_ctx["can_edit"] is False


@pytest.mark.asyncio
async def test_detail_extras_merges_into_context():
    """Extras callable's return dict merges into context, last-write-wins.

    Tests can override the base `spec.name` binding via extras (e.g. user
    binds under `target_user`)."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    async def extras(*, target, request, requesting_user, **_):
        return {
            "extra_flag": True,
            "widget": "projection",  # overrides base spec.name binding
        }

    context = await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4()),
        extras=extras,
    )

    assert context["extra_flag"] is True
    assert context["widget"] == "projection"  # last-write-wins


@pytest.mark.asyncio
async def test_detail_extras_receives_extra_kwargs():
    """`extra_kwargs` is forwarded to the extras callable, in addition to
    `target` / `request` / `requesting_user`."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)
    captured = {}

    async def extras(*, target, request, requesting_user, side_repo, **_):
        captured["target"] = target
        captured["side_repo"] = side_repo
        return {}

    side_repo = object()
    await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4()),
        extras=extras,
        extra_kwargs={"side_repo": side_repo},
    )

    assert captured["target"] is target
    assert captured["side_repo"] is side_repo


@pytest.mark.asyncio
async def test_detail_target_not_found_raises_not_found():
    spec = _top_level_spec()
    repo = _FakeRepo()
    with pytest.raises(NotFoundError):
        await handle_detail(
            spec,
            request=SimpleNamespace(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=SimpleNamespace(id=uuid4()),
        )


@pytest.mark.asyncio
async def test_detail_anonymous_viewer_supported():
    """`requesting_user=None` works — public-detail entities (no
    read_user_dep) can pass None."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    context = await handle_detail(
        spec,
        request=SimpleNamespace(),
        target_id=target_id,
        repo=repo,
        requesting_user=None,
    )

    assert context["current_user"] is None


# --- make_detail_handler factory -----------------------------------------


def test_make_detail_handler_signature():
    spec = _top_level_spec(write_authz=None)
    handler = make_detail_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "request",
        "widget_id",
        "repo",
        "requesting_user",
    }


def test_make_detail_handler_includes_extra_repos_in_signature():
    """`extra_repos=` adds typed params so `mount_detail`'s introspection
    wires them via the repo type registry — same shape as a hand-written
    multi-repo detail handler."""

    class _SideRepo:
        pass

    spec = _top_level_spec(write_authz=None)
    handler = make_detail_handler(spec, extra_repos=(("side_repo", _SideRepo),))
    sig = inspect.signature(handler)
    assert "side_repo" in sig.parameters
    assert sig.parameters["side_repo"].annotation is _SideRepo


def test_make_detail_handler_name_includes_entity():
    spec = _top_level_spec(write_authz=None)
    handler = make_detail_handler(spec)
    assert handler.__name__ == "_handle_get_widget_detail"


@pytest.mark.asyncio
async def test_make_detail_handler_delegates_to_handle_detail():
    """The factory-built handler invokes `handle_detail` with the spec
    bound and `extra_repos` forwarded into `extra_kwargs`."""
    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    class _SideRepo:
        pass

    side_repo = _SideRepo()
    captured = {}

    async def extras(*, target, request, requesting_user, side_repo, **_):
        captured["side_repo"] = side_repo
        return {"extra_flag": True}

    handler = make_detail_handler(
        spec, extras=extras, extra_repos=(("side_repo", _SideRepo),)
    )
    context = await handler(
        request=SimpleNamespace(),
        widget_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4()),
        side_repo=side_repo,
    )

    assert context["widget"] is target
    assert context["extra_flag"] is True
    assert captured["side_repo"] is side_repo
