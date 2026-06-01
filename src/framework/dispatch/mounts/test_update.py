"""Tests for `handle_update` and `make_update_handler` in `mounts/update.py`.

Moved from `src/framework/dispatch/test_handlers.py`.
"""

import inspect
from dataclasses import dataclass as _dc
from typing import Any as _Any
from uuid import uuid4

import pytest
from pydantic import BaseModel as _BaseModel

from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.mounts.conftest import (
    FakeAuditRepo,
    FakeRepo,
    ParentRow,
    make_audit,
    make_user,
    parent_spec,
)
from src.framework.dispatch.mounts.update import handle_update, make_update_handler
from src.framework.http.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.framework.persistence.polymorphic import DiscriminatorRegistry

# --- Helper: extended repo for update tests --------------------------------


def _update_fake_repo() -> FakeRepo:
    """`FakeRepo` extended with `patch` for the framework's update path."""
    repo = FakeRepo()
    # Also add create / add_child / create_polymorphic for compat with _create_fake_repo
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


class _AnyRow:
    """Flexible fixture row used by update tests — accepts any kwargs."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, "id"):
            self.id = uuid4()


class _UpdatePayload(_BaseModel):
    practice_name: str | None = None
    location_city: str | None = None


# --- Polymorphic helpers --------------------------------------------------


@_dc(frozen=True)
class _FixtureKindSpec:
    kind: str
    detail_model: type
    detail_fields: tuple[str, ...]
    detail_relationship: str


class _RedDetail:
    def __init__(self, redness: int = 0):
        self.redness = redness


class _BlueDetail:
    def __init__(self, blueness: int = 0):
        self.blueness = blueness


class _RedUpdatePayload(_BaseModel):
    kind: str
    redness: int | None = None


class _BlueUpdatePayload(_BaseModel):
    kind: str
    blueness: int | None = None


# --- Happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_top_level_partial_patch_via_exclude_unset():
    """`exclude_unset` — only explicitly-set fields are patched."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    target = _AnyRow(id=target_id, practice_name="Old", location_city="OldCity")
    repo.seed(_AnyRow, target)
    audit_repo = FakeAuditRepo()

    await handle_update(
        spec,
        target_id=target_id,
        payload=_UpdatePayload(practice_name="New"),  # location_city unset
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=make_user(),
    )

    assert target.practice_name == "New"
    assert target.location_city == "OldCity"  # unchanged
    assert len(audit_repo.calls) == 1
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
        audit=make_audit(),
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
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(),
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

    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        write_authz=authz,
        routes=RouteSet(update=True),
        update_adapter=__import__("pydantic").TypeAdapter(_UpdatePayload),
    )
    repo = _update_fake_repo()
    parent_id = uuid4()
    parent_obj = ParentRow(id=parent_id)
    repo.seed(ps.model, parent_obj)
    child_id = uuid4()
    child = _AnyRow(id=child_id, parent_id=parent_id, practice_name="Old")
    repo.seed(_AnyRow, child)

    await handle_update(
        spec,
        target_id=child_id,
        parent_id=parent_id,
        payload=_UpdatePayload(practice_name="New"),
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(),
    )

    assert seen_authz == [parent_obj]
    assert child.practice_name == "New"


@pytest.mark.asyncio
async def test_update_subentity_parent_fk_mismatch_404():
    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        routes=RouteSet(update=True),
        update_adapter=__import__("pydantic").TypeAdapter(_UpdatePayload),
    )
    repo = _update_fake_repo()
    parent_id = uuid4()
    other_parent_id = uuid4()
    child_id = uuid4()
    repo.seed(ps.model, ParentRow(id=parent_id))
    repo.seed(ps.model, ParentRow(id=other_parent_id))
    repo.seed(_AnyRow, _AnyRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_update(
            spec,
            target_id=child_id,
            parent_id=other_parent_id,
            payload=_UpdatePayload(),
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


# --- Polymorphic update --------------------------------------------------


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
        audit=make_audit(),
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
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(),
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
        audit=make_audit(),
        discriminator=registry,
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    target = _AnyRow(id=target_id, kind="red", red_detail=_RedDetail())
    repo.seed(_AnyRow, target)
    audit_repo = FakeAuditRepo()

    with pytest.raises(BadRequestError):
        await handle_update(
            spec,
            target_id=target_id,
            payload=_BlueUpdatePayload(kind="blue", blueness=5),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
        )

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
        audit=make_audit(),
    )
    with pytest.raises(NotFoundError):
        await handle_update(
            spec,
            target_id=uuid4(),
            payload=_UpdatePayload(),
            repo=_update_fake_repo(),
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
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
        audit=make_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    repo.seed(_AnyRow, _AnyRow(id=target_id))
    audit_repo = FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_update(
            spec,
            target_id=target_id,
            payload=_UpdatePayload(),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
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
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


# --- make_update_handler factory ------------------------------------------


def test_make_update_handler_top_level_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
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
    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
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
        audit=make_audit(),
    )
    handler = make_update_handler(spec)
    assert handler.__name__ == "_handle_update_widget"


# --- payload_authz for update -------------------------------------------


class _StubOrgRepo:
    """Stand-in typed repo passed through `payload_authz_repos`."""


@pytest.mark.asyncio
async def test_update_invokes_payload_authz_after_404_before_patch():
    """`payload_authz` fires after the target loads and before the patch."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    repo = _update_fake_repo()
    target_id = uuid4()
    repo.seed(_AnyRow, _AnyRow(id=target_id, practice_name="Old"))
    audit_repo = FakeAuditRepo()

    async def authz(*, payload, requesting_user):
        raise ForbiddenError(detail="payload says no")

    with pytest.raises(ForbiddenError):
        await handle_update(
            spec,
            target_id=target_id,
            payload=_UpdatePayload(practice_name="New"),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
            payload_authz=authz,
        )

    assert repo.patched == []
    assert audit_repo.calls == []


@pytest.mark.asyncio
async def test_update_payload_authz_skipped_when_target_missing():
    """When the target 404s, `payload_authz` is never called."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    seen: list[_Any] = []

    async def authz(*, payload, requesting_user):
        seen.append(payload)

    with pytest.raises(NotFoundError):
        await handle_update(
            spec,
            target_id=uuid4(),  # never seeded
            payload=_UpdatePayload(),
            repo=_update_fake_repo(),
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
            payload_authz=authz,
        )

    assert seen == []


def test_make_update_handler_with_payload_authz_signature():
    """Synthesized update-handler signature includes declared
    `payload_authz_repos` kwargs as typed params."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )

    async def authz(**_kw):  # pragma: no cover
        return None

    handler = make_update_handler(
        spec,
        payload_authz=authz,
        payload_authz_repos=(("organization_repo", _StubOrgRepo),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _StubOrgRepo
