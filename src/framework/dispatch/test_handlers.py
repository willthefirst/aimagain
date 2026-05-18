"""Framework tests for `src/framework/dispatch/handlers.py`.

These pin the generic handler behavior against fixture specs and
fixture models — independent of any production entity. The per-entity
spec-correctness suites (`src/domain/specs/test_<entity>.py`)
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
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

import pytest


def _request_stub(query: str = "") -> SimpleNamespace:
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


from src.framework.audit.core import AuditAction, AuditedResource
from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.handlers import handle_delete, make_delete_handler
from src.framework.http.exceptions import ForbiddenError, NotFoundError

# --- Fixture model + repo --------------------------------------------------


@dataclass
class _FixtureRow:
    """Stand-in ORM row: just needs `id` plus optional parent FK column.

    `owner_id` defaults to None so tests that don't care about ownership
    can ignore it; the spec's default `owner_attr="owner_id"` reads it
    in `handle_detail`'s `is_self` derivation."""

    id: UUID
    parent_id: UUID | None = None
    owner_id: UUID | None = None
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


def _user(*, id_: UUID | None = None, is_superuser: bool = False) -> SimpleNamespace:
    """User-stub factory that always carries `is_superuser`. Mirrors the
    same-named helper in `test__authz.py`. The framework's auto-injection
    of `can_admin_actions` reads `user.is_superuser`, so every stub the
    detail/list handlers see needs the field present."""
    return SimpleNamespace(id=id_ or uuid4(), is_superuser=is_superuser)


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
    user = _user()
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
    user = _user()

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
    user = _user()

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
        requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
        requesting_user=_user(),
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

from src.framework.dispatch.entity_spec import RelatedListSubresource  # noqa: F401
from src.framework.dispatch.handlers import handle_create, make_create_handler
from src.framework.persistence.polymorphic import DiscriminatorRegistry


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
    user = _user()

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
    user = _user()

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
    user = _user()

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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
    user = _user()

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
            requesting_user=_user(),
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
            requesting_user=_user(),
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


from src.framework.dispatch.handlers import (  # noqa: E402
    handle_update,
    make_update_handler,
)
from src.framework.http.exceptions import BadRequestError  # noqa: E402


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
        requesting_user=_user(),
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
        requesting_user=_user(),
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
        requesting_user=_user(),
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
            requesting_user=_user(),
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
        requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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
            requesting_user=_user(),
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


from src.framework.dispatch.handlers import (  # noqa: E402
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
    user = _user()
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
    user = _user()

    await handle_get_edit_form(
        spec,
        request=_request_stub(),
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
            request=_request_stub(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=_user(),
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
            request=_request_stub(),
            target_id=target_id,
            repo=repo,
            requesting_user=_user(),
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
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=_user(),
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
    user = _user()
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


# --- handle_get_new_form framework tests ---------------------------------


from src.framework.dispatch.handlers import (  # noqa: E402
    handle_get_new_form,
    make_new_form_handler,
)


class _FormSchema(_BaseModel):
    name: str = ""


@_dc(frozen=True)
class _FixtureNewKindSpec:
    """Stands in for `PostKindSpec` — only `create_template` is
    load-bearing for the new-form path."""

    create_template: str


@pytest.mark.asyncio
async def test_new_form_top_level_happy_path():
    """Non-polymorphic: returns request + current_user + schema class."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = _user()
    request = SimpleNamespace()

    context = await handle_get_new_form(spec, request=request, requesting_user=user)

    assert context["request"] is request
    assert context["current_user"] is user
    # Bound from the unwrapped class so templates can read `model_fields`.
    assert context["schema"] is _FormSchema
    assert "template_name" not in context


@pytest.mark.asyncio
async def test_new_form_merges_static_context():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
        static_context={"LABELS": {"a": "A"}},
    )

    context = await handle_get_new_form(
        spec, request=_request_stub(), requesting_user=_user()
    )

    assert context["LABELS"] == {"a": "A"}


@pytest.mark.asyncio
async def test_new_form_polymorphic_uses_kind_create_template():
    """Polymorphic: template_name comes from
    `spec.discriminator[kind].create_template`; no schema key (kind-specific
    create templates handle their own field rendering)."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureNewKindSpec(create_template="paintings/new_red.html"),
            "blue": _FixtureNewKindSpec(create_template="paintings/new_blue.html"),
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

    context = await handle_get_new_form(
        spec,
        request=_request_stub(),
        requesting_user=_user(),
        kind="blue",
    )

    assert context["template_name"] == "paintings/new_blue.html"
    assert "schema" not in context


@pytest.mark.asyncio
async def test_new_form_polymorphic_no_kind_leaves_template_unset():
    """Polymorphic + `kind=None`: handler does NOT set `template_name`,
    so the route falls through to `spec.form_template` (the kind
    picker, conventionally `<collection>/form_new.html`). A previous
    revision defaulted to the first registered kind's template silently;
    that hid the kind-choice UX behind a default."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureNewKindSpec(create_template="paintings/new_red.html"),
            "blue": _FixtureNewKindSpec(create_template="paintings/new_blue.html"),
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

    context = await handle_get_new_form(
        spec, request=_request_stub(), requesting_user=_user(), kind=None
    )

    assert "template_name" not in context


# --- make_new_form_handler factory ----------------------------------------


def test_make_new_form_handler_signature_non_polymorphic():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    handler = make_new_form_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {"request", "requesting_user"}


def test_make_new_form_handler_signature_polymorphic_includes_kind():
    registry = DiscriminatorRegistry(
        column="kind",
        specs={"red": _FixtureNewKindSpec(create_template="x.html")},
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=_audit(),
        discriminator=registry,
    )
    handler = make_new_form_handler(spec)
    sig = inspect.signature(handler)
    assert "kind" in sig.parameters
    # `repo` is omitted — new-form doesn't load a target.
    assert "repo" not in sig.parameters


def test_make_new_form_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    handler = make_new_form_handler(spec)
    assert handler.__name__ == "_handle_get_widget_new_form"


@pytest.mark.asyncio
async def test_make_new_form_handler_delegates_to_handle_get_new_form():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = _user()
    request = SimpleNamespace()

    handler = make_new_form_handler(spec)
    context = await handler(request=request, requesting_user=user)

    assert context["schema"] is _FormSchema
    assert context["current_user"] is user


# --- form_extras (create- + edit-form extras) framework tests ------------


@pytest.mark.asyncio
async def test_new_form_invokes_form_extras_with_target_none():
    """`handle_get_new_form` calls the `extras` callable with
    `target=None` (no row is loaded on the create path) and merges the
    returned dict into the context."""
    captured: dict[str, Any] = {}

    async def extras(**kwargs):
        captured.update(kwargs)
        return {"orgs": ["a", "b"]}

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = _user()
    request = SimpleNamespace()

    context = await handle_get_new_form(
        spec,
        request=request,
        requesting_user=user,
        extras=extras,
        extra_kwargs={"organization_repo": "REPO_SENTINEL"},
    )

    assert captured["target"] is None
    assert captured["request"] is request
    assert captured["requesting_user"] is user
    assert captured["organization_repo"] == "REPO_SENTINEL"
    assert context["orgs"] == ["a", "b"]


@pytest.mark.asyncio
async def test_edit_form_invokes_form_extras_with_target_row():
    """`handle_get_edit_form` calls the `extras` callable with the
    loaded row bound to `target` and merges the returned dict into the
    context (last-write-wins over spec.static_context)."""
    captured: dict[str, Any] = {}

    async def extras(**kwargs):
        captured.update(kwargs)
        return {"orgs": ["x"]}

    spec = _top_level_spec(write_authz=None)
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)
    user = _user()
    request = SimpleNamespace()

    context = await handle_get_edit_form(
        spec,
        request=request,
        target_id=target_id,
        repo=repo,
        requesting_user=user,
        extras=extras,
        extra_kwargs={"organization_repo": "REPO_SENTINEL"},
    )

    assert captured["target"] is target
    assert captured["request"] is request
    assert captured["requesting_user"] is user
    assert captured["organization_repo"] == "REPO_SENTINEL"
    assert context["orgs"] == ["x"]
    assert context["widget"] is target


def test_make_edit_form_handler_includes_extra_repos_in_signature():
    """`extra_repos=` declared on the factory adds typed-repo kwargs to
    the synthesized signature so FastAPI's DI can resolve them."""

    class _RepoMarker:
        pass

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
    )

    async def extras(**_):
        return {}

    handler = make_edit_form_handler(
        spec,
        extras=extras,
        extra_repos=(("organization_repo", _RepoMarker),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _RepoMarker


def test_make_new_form_handler_includes_extra_repos_in_signature():
    class _RepoMarker:
        pass

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )

    async def extras(**_):
        return {}

    handler = make_new_form_handler(
        spec,
        extras=extras,
        extra_repos=(("organization_repo", _RepoMarker),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _RepoMarker


# --- handle_detail framework tests ---------------------------------------


from src.framework.dispatch.handlers import (  # noqa: E402
    handle_detail,
    make_detail_handler,
)


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
    user = _user()

    context = await handle_detail(
        spec,
        request=_request_stub(),
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
    owner = _user(id_=owner_id)
    stranger = _user()

    # _FixtureRow doesn't have owner_id; simulate by setattr.
    target = _FixtureRow(id=target_id)
    target.owner_id = owner_id  # type: ignore[attr-defined]
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    owner_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=owner,
    )
    assert owner_ctx["can_edit"] is True

    stranger_ctx = await handle_detail(
        spec,
        request=_request_stub(),
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
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=_user(),
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
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=_user(),
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
            request=_request_stub(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=_user(),
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
        request=_request_stub(),
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
        request=_request_stub(),
        widget_id=target_id,
        repo=repo,
        requesting_user=_user(),
        side_repo=side_repo,
    )

    assert context["widget"] is target
    assert context["extra_flag"] is True
    assert captured["side_repo"] is side_repo


# --- handle_list / make_list_handler --------------------------------------


async def test_handle_list_returns_items_under_url_collection():
    """The framework binds the list under `spec.url_collection`, not
    `spec.name` — the existing list templates read `{{ widgets }}` etc."""
    spec = _top_level_spec()
    row_a = _FixtureRow(id=uuid4())
    row_b = _FixtureRow(id=uuid4())

    class _ListRepo:
        async def list_widgets(self, **_kwargs):
            return [row_a, row_b]

    from src.framework.dispatch.handlers import handle_list

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )
    assert context["widgets"] == [row_a, row_b]
    assert context["current_user"] is None


async def test_handle_list_echoes_filter_values_as_selected():
    """For each filter passed in, the context carries `selected_<name>`
    so the filter form can preselect the active value."""
    spec = _top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            return []

    from src.framework.dispatch.handlers import handle_list

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={"kind": "alpha", "state": None},
    )
    assert context["selected_kind"] == "alpha"
    assert context["selected_state"] is None


async def test_handle_list_threads_filter_values_into_repo_call():
    """The repo receives every `filter_values` entry as a kwarg."""
    spec = _top_level_spec()
    captured: dict = {}

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.update(kwargs)
            return []

    from src.framework.dispatch.handlers import handle_list

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={"kind": "beta"},
    )
    # `offset` + `limit` come from the pagination layer (`page=1`,
    # `per_page=DEFAULT_PAGE_SIZE=25`, asked-for-rows=`per_page + 1`).
    assert captured == {"kind": "beta", "offset": 0, "limit": 26}


async def test_handle_list_extras_merges_into_context():
    """`extras` is post-fetch; its return dict layers over the base
    context (last-write-wins — same semantics as handle_detail)."""
    spec = _top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **_):
            return ["a", "b"]

    async def extras(*, items, **_):
        return {"extra_count": len(items), "current_user": "overridden"}

    from src.framework.dispatch.handlers import handle_list

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
        extras=extras,
    )
    assert context["extra_count"] == 2
    assert context["current_user"] == "overridden"


def test_make_list_handler_signature_includes_filters_and_repos():
    """The factory must synthesize a typed signature so mount_list's
    introspection wires the filter query params and the typed repos."""
    from src.framework.dispatch.entity_spec import QueryParam
    from src.framework.dispatch.handlers import make_list_handler

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        filters=(QueryParam("kind", str | None, None),),
    )

    class _SideRepo:
        pass

    handler = make_list_handler(spec, extra_repos=(("side_repo", _SideRepo),))
    sig = inspect.signature(handler)
    names = list(sig.parameters)
    assert "request" in names
    assert "kind" in names
    assert "repo" in names
    assert "requesting_user" in names
    assert "side_repo" in names
    assert handler.__name__ == "_handle_list_widget"


# --- Viewer-flag + projection auto-injection (handle_detail) -------------


def _is_self_or_admin(actor, target) -> bool:
    """Stand-in `private_field_predicate`: viewer is self or admin."""
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    subject_id = getattr(target, "owner_id", None) or getattr(target, "id", None)
    return getattr(actor, "id", None) == subject_id


@pytest.mark.asyncio
async def test_detail_injects_is_self_for_owned_resource():
    """`is_self` compares `target.<owner_attr>` to viewer.id when
    `spec.owner_attr` is set (the owned-resource rule)."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        owner_attr="owner_id",
        audit=_audit(),
    )
    target_id = uuid4()
    owner_id = uuid4()
    target = _FixtureRow(id=target_id)
    target.owner_id = owner_id  # type: ignore[attr-defined]
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    owner = SimpleNamespace(id=owner_id, is_superuser=False)
    stranger = SimpleNamespace(id=uuid4(), is_superuser=False)

    owner_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=owner,
    )
    stranger_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=stranger,
    )
    anon_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=None,
    )

    assert owner_ctx["is_self"] is True
    assert stranger_ctx["is_self"] is False
    assert anon_ctx["is_self"] is False


@pytest.mark.asyncio
async def test_detail_injects_is_self_for_user_like_resource():
    """When `owner_attr=None` (the resource IS the user), `is_self`
    reduces to `target.id == viewer.id`."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        owner_attr=None,
        audit=_audit(),
    )
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    self_viewer = SimpleNamespace(id=target_id, is_superuser=False)
    other_viewer = SimpleNamespace(id=uuid4(), is_superuser=False)

    self_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=self_viewer,
    )
    other_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=other_viewer,
    )

    assert self_ctx["is_self"] is True
    assert other_ctx["is_self"] is False


@pytest.mark.asyncio
async def test_detail_injects_can_admin_actions_excludes_self():
    """`can_admin_actions` is `is_admin(viewer) and not is_self` —
    admins lose the flag on their own row so they can't act on themselves."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        owner_attr=None,
        audit=_audit(),
    )
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    admin = SimpleNamespace(id=uuid4(), is_superuser=True)
    self_admin = SimpleNamespace(id=target_id, is_superuser=True)
    plain = SimpleNamespace(id=uuid4(), is_superuser=False)

    admin_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=admin,
    )
    self_admin_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=self_admin,
    )
    plain_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=plain,
    )

    assert admin_ctx["can_admin_actions"] is True
    assert self_admin_ctx["can_admin_actions"] is False
    assert plain_ctx["can_admin_actions"] is False


@pytest.mark.asyncio
async def test_detail_injects_can_view_private_when_predicate_set():
    """`can_view_private` is the spec's `private_field_predicate`
    evaluated against (viewer, target). Absent when no predicate."""
    spec_with = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        private_fields=("secret",),
        private_field_predicate=_is_self_or_admin,
        audit=_audit(),
    )
    spec_without = _top_level_spec()  # no private_field_predicate
    target_id = uuid4()
    target = _FixtureRow(id=target_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    self_viewer = SimpleNamespace(id=target_id, is_superuser=False)
    stranger = SimpleNamespace(id=uuid4(), is_superuser=False)

    self_ctx = await handle_detail(
        spec_with,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=self_viewer,
    )
    stranger_ctx = await handle_detail(
        spec_with,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=stranger,
    )
    without_ctx = await handle_detail(
        spec_without,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=stranger,
    )

    assert self_ctx["can_view_private"] is True
    assert stranger_ctx["can_view_private"] is False
    assert "can_view_private" not in without_ctx


@pytest.mark.asyncio
async def test_detail_injects_target_projection_when_public_fields_set():
    """`target_<name>` is a `project_view` dict gated by the spec's
    predicate. Omits private fields for non-privileged viewers."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        public_fields=("id",),
        private_fields=("parent_id",),
        private_field_predicate=_is_self_or_admin,
        audit=_audit(),
    )
    target_id = uuid4()
    parent_id = uuid4()
    target = _FixtureRow(id=target_id, parent_id=parent_id)
    repo = _FakeRepo()
    repo.seed(_FixtureRow, target)

    self_viewer = SimpleNamespace(id=target_id, is_superuser=False)
    stranger = SimpleNamespace(id=uuid4(), is_superuser=False)

    self_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=self_viewer,
    )
    stranger_ctx = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=stranger,
    )

    assert self_ctx["target_widget"] == {"id": target_id, "parent_id": parent_id}
    assert stranger_ctx["target_widget"] == {"id": target_id}


@pytest.mark.asyncio
async def test_detail_no_projection_when_public_fields_unset():
    """Without `public_fields`, no `target_<name>` key is injected."""
    spec = _top_level_spec()
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=False),
    )

    assert "target_widget" not in context


# --- Viewer-flag + exclude-self auto-injection (handle_list) -------------


@pytest.mark.asyncio
async def test_handle_list_injects_can_admin_actions():
    """`can_admin_actions` is `is_admin(viewer)` on list pages (no
    `is_self` semantics — every row is some other entity)."""
    spec = _top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **_):
            return []

    from src.framework.dispatch.handlers import handle_list

    admin_ctx = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=True),
        filter_values={},
    )
    plain_ctx = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=False),
        filter_values={},
    )
    anon_ctx = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )

    assert admin_ctx["can_admin_actions"] is True
    assert plain_ctx["can_admin_actions"] is False
    assert anon_ctx["can_admin_actions"] is False


@pytest.mark.asyncio
async def test_handle_list_passes_exclude_self_when_spec_opts_in():
    """`list_exclude_self=True` threads `exclude_self=requesting_user`
    into the repo's list method. Anonymous viewers skip the kwarg."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        routes=RouteSet(list=True),
        list_exclude_self=True,
    )
    captured: list[dict] = []

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.append(kwargs)
            return []

    from src.framework.dispatch.handlers import handle_list

    viewer = SimpleNamespace(id=uuid4(), is_superuser=False)
    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=viewer,
        filter_values={},
    )
    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )

    # `offset` + `limit` come from the pagination layer (page 1 of 25).
    assert captured[0] == {"exclude_self": viewer, "offset": 0, "limit": 26}
    assert captured[1] == {"offset": 0, "limit": 26}


@pytest.mark.asyncio
async def test_handle_list_omits_exclude_self_when_spec_opts_out():
    """Without `list_exclude_self=True`, the repo call carries no
    `exclude_self` kwarg — existing entities are unaffected."""
    spec = _top_level_spec()
    captured: list[dict] = []

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.append(kwargs)
            return []

    from src.framework.dispatch.handlers import handle_list

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=False),
        filter_values={"kind": "alpha"},
    )

    # `offset` + `limit` come from the pagination layer (page 1 of 25).
    assert captured[0] == {"kind": "alpha", "offset": 0, "limit": 26}
    assert "exclude_self" not in captured[0]


@pytest.mark.asyncio
async def test_handle_list_falls_back_to_list_default_when_no_bespoke_method():
    """When the repo has no `list_<collection>` method, `handle_list`
    falls through to `BaseRepository.list_default(spec.model,
    order_by=spec.list_order_by, **kwargs)` — the framework default
    for trivial listings."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        routes=RouteSet(list=True),
        list_order_by="ORDER_BY_SENTINEL",
    )
    captured: dict = {}

    class _DefaultOnlyRepo:
        async def list_default(self, model, *, order_by, **kwargs):
            captured["model"] = model
            captured["order_by"] = order_by
            captured["kwargs"] = kwargs
            return []

    from src.framework.dispatch.handlers import handle_list

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_DefaultOnlyRepo(),
        requesting_user=None,
        filter_values={},
    )

    assert captured["model"] is _FixtureRow
    assert captured["order_by"] == "ORDER_BY_SENTINEL"
    # `offset` + `limit` come from the pagination layer (page 1 of 25).
    assert captured["kwargs"] == {"offset": 0, "limit": 26}


@pytest.mark.asyncio
async def test_handle_list_fallback_raises_when_no_order_by():
    """No bespoke list method AND no `list_order_by` is a misconfiguration.
    The framework can't pick an ordering for the caller, so it raises a
    clear error instead of executing a random-order list."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        routes=RouteSet(list=True),
    )

    class _DefaultOnlyRepo:
        async def list_default(self, model, *, order_by, **kwargs):  # pragma: no cover
            return []

    from src.framework.dispatch.handlers import handle_list

    with pytest.raises(ValueError, match="list_order_by"):
        await handle_list(
            spec,
            request=_request_stub(),
            repo=_DefaultOnlyRepo(),
            requesting_user=None,
            filter_values={},
        )


# --- Spec construction-time validation -----------------------------------


def test_public_fields_without_predicate_rejected():
    """Declaring `public_fields` without a `private_field_predicate`
    would let the projection silently pass every private field."""
    with pytest.raises(ValueError, match="private_field_predicate"):
        EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=_FixtureRow,
            public_fields=("id",),
            audit=_audit(),
        )


def test_list_exclude_self_requires_list_route():
    """`list_exclude_self` is only consumed by handle_list — without a
    list route the flag would be dead."""
    with pytest.raises(ValueError, match="routes.list"):
        EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=_FixtureRow,
            audit=_audit(),
            list_exclude_self=True,
            routes=RouteSet(detail=True),
        )


# --- static_context spec field --------------------------------------------


@pytest.mark.asyncio
async def test_handle_detail_merges_static_context():
    """`spec.static_context` entries land in the detail context, after
    auto-injected viewer keys and before extras run."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        static_context={"widget_kinds": ("alpha", "beta")},
    )
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=_user(),
    )

    assert context["widget_kinds"] == ("alpha", "beta")


@pytest.mark.asyncio
async def test_handle_list_merges_static_context():
    """`spec.static_context` entries land in the list context, after the
    base context and `selected_<filter>` echoes."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        static_context={"widget_kinds": ("alpha", "beta")},
    )

    class _ListRepo:
        async def list_widgets(self, **_):
            return []

    from src.framework.dispatch.handlers import handle_list

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )

    assert context["widget_kinds"] == ("alpha", "beta")


@pytest.mark.asyncio
async def test_extras_can_override_static_context():
    """Extras runs after static_context merges in; last-write-wins lets
    an entity-specific extras override a static value if needed."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        static_context={"flag": "from-static"},
    )
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    async def extras(**_):
        return {"flag": "from-extras"}

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=_user(),
        extras=extras,
    )

    assert context["flag"] == "from-extras"


def test_static_context_default_is_empty_dict():
    """Default is empty; absent declaration means no extra keys land."""
    spec = _top_level_spec()
    assert spec.static_context == {}


# --- delete_forbid_self ---------------------------------------------------


@pytest.mark.asyncio
async def test_handle_delete_rejects_self_when_flag_set():
    """`delete_forbid_self=True` blocks the request with 403 if the URL
    target id equals the requesting user's id. Same logic that used to
    live in `handle_delete_user` (bespoke), now framework-driven."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        routes=RouteSet(delete=True),
        delete_forbid_self=True,
    )
    actor_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=actor_id))
    audit_repo = _FakeAuditRepo()
    actor = _user(id_=actor_id, is_superuser=True)

    with pytest.raises(ForbiddenError):
        await handle_delete(
            spec,
            target_id=actor_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=actor,
        )
    # Nothing deleted, no audit row written.
    assert repo.deleted == []
    assert audit_repo.calls == []


@pytest.mark.asyncio
async def test_handle_delete_allows_non_self_when_flag_set():
    """The flag fires only on self-target — admins can still delete
    other users' rows."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_FixtureRow,
        audit=_audit(),
        routes=RouteSet(delete=True),
        delete_forbid_self=True,
    )
    target_id = uuid4()
    repo = _FakeRepo()
    repo.seed(_FixtureRow, _FixtureRow(id=target_id))

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=_FakeAuditRepo(),
        requesting_user=_user(is_superuser=True),
    )
    assert len(repo.deleted) == 1


def test_delete_forbid_self_requires_delete_route():
    """`delete_forbid_self` is consumed only by handle_delete — without
    a delete route the flag would be dead."""
    with pytest.raises(ValueError, match="routes.delete"):
        EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=_FixtureRow,
            audit=_audit(),
            delete_forbid_self=True,
            routes=RouteSet(detail=True),
        )


# --- StateAxis.forbid_self (mount-time wrapper) --------------------------


@pytest.mark.asyncio
async def test_state_axis_forbid_self_wrapper_rejects_self_target():
    """The `forbid_self` axis flag wraps the resolved handler so a
    self-target invocation raises 403 before the inner handler runs."""
    from src.framework.dispatch.resource_routes import _wrap_state_axis_with_self_guard

    inner_called = False

    async def inner(*, widget_id, requesting_user, payload):
        nonlocal inner_called
        inner_called = True
        return None

    wrapped = _wrap_state_axis_with_self_guard(
        inner, id_param="widget_id", axis_name="activation"
    )
    actor_id = uuid4()
    actor = _user(id_=actor_id)

    with pytest.raises(ForbiddenError, match="activation"):
        await wrapped(widget_id=actor_id, requesting_user=actor, payload=None)
    assert inner_called is False


@pytest.mark.asyncio
async def test_state_axis_forbid_self_wrapper_lets_other_targets_through():
    """The wrapper is a no-op when target_id != requesting_user.id."""
    from src.framework.dispatch.resource_routes import _wrap_state_axis_with_self_guard

    inner_called = False

    async def inner(*, widget_id, requesting_user, payload):
        nonlocal inner_called
        inner_called = True
        return "ok"

    wrapped = _wrap_state_axis_with_self_guard(
        inner, id_param="widget_id", axis_name="activation"
    )

    result = await wrapped(
        widget_id=uuid4(),
        requesting_user=_user(),
        payload=None,
    )
    assert result == "ok"
    assert inner_called is True
