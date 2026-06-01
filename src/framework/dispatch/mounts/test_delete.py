"""Tests for `handle_delete` and `make_delete_handler` in `mounts/delete.py`.

Moved from `src/framework/dispatch/test_handlers.py`.
"""

import inspect
from uuid import uuid4

import pytest

from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.mounts.conftest import (
    FakeAuditRepo,
    FakeRepo,
    FixtureRow,
    ParentRow,
    child_spec,
    make_audit,
    make_user,
    top_level_spec,
)
from src.framework.dispatch.mounts.delete import handle_delete, make_delete_handler
from src.framework.http.exceptions import ForbiddenError, NotFoundError

# --- Happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_top_level_delete_happy_path():
    """Standard delete with no auth predicate: target loaded, deleted,
    audit row written, commit fired."""
    from src.framework.audit.core import AuditAction

    spec = top_level_spec(write_authz=None)
    repo = FakeRepo()
    audit_repo = FakeAuditRepo()
    user = make_user()
    target_id = uuid4()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

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

    spec = top_level_spec(write_authz=authz)
    repo = FakeRepo()
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo.seed(FixtureRow, target)
    user = make_user()

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=FakeAuditRepo(),
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
    cs = child_spec()
    ps = cs.parent
    repo = FakeRepo()
    parent_id = uuid4()
    child_id = uuid4()
    repo.seed(ps.model, ParentRow(id=parent_id))
    repo.seed(cs.model, FixtureRow(id=child_id, parent_id=parent_id))
    audit_repo = FakeAuditRepo()
    user = make_user()

    await handle_delete(
        cs,
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

    cs = child_spec(write_authz=authz)
    parent_id = uuid4()
    child_id = uuid4()
    parent = ParentRow(id=parent_id)
    child = FixtureRow(id=child_id, parent_id=parent_id)
    repo = FakeRepo()
    repo.seed(cs.parent.model, parent)
    repo.seed(cs.model, child)

    await handle_delete(
        cs,
        target_id=child_id,
        parent_id=parent_id,
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(),
    )

    assert len(seen) == 1
    assert seen[0] is parent  # against parent, not child


# --- Error paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_target_not_found_raises_not_found():
    spec = top_level_spec()
    repo = FakeRepo()  # empty
    with pytest.raises(NotFoundError):
        await handle_delete(
            spec,
            target_id=uuid4(),
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )
    assert repo.deleted == []


@pytest.mark.asyncio
async def test_subentity_parent_fk_mismatch_raises_not_found():
    """Child exists but belongs to a different parent — 404, never a hint
    that the child is real but elsewhere."""
    cs = child_spec()
    parent_id = uuid4()
    other_parent_id = uuid4()
    child_id = uuid4()
    repo = FakeRepo()
    repo.seed(cs.parent.model, ParentRow(id=parent_id))
    repo.seed(cs.parent.model, ParentRow(id=other_parent_id))
    repo.seed(cs.model, FixtureRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_delete(
            cs,
            target_id=child_id,
            parent_id=other_parent_id,  # different parent
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_subentity_parent_not_found_raises_not_found():
    cs = child_spec()
    parent_id = uuid4()
    child_id = uuid4()
    repo = FakeRepo()
    # Child seeded but parent not seeded.
    repo.seed(cs.model, FixtureRow(id=child_id, parent_id=parent_id))

    with pytest.raises(NotFoundError):
        await handle_delete(
            cs,
            target_id=child_id,
            parent_id=parent_id,
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_subentity_without_parent_id_raises_value_error():
    """Spec has parent but caller didn't supply parent_id — programming
    error, fail loudly."""
    cs = child_spec()
    child_id = uuid4()
    repo = FakeRepo()
    repo.seed(cs.model, FixtureRow(id=child_id))

    with pytest.raises(ValueError, match="parent"):
        await handle_delete(
            cs,
            target_id=child_id,
            parent_id=None,
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_write_authz_raises_propagates_no_audit_no_commit():
    """If the predicate raises, no audit row + no commit."""

    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    spec = top_level_spec(write_authz=authz)
    repo = FakeRepo()
    target_id = uuid4()
    repo.seed(FixtureRow, FixtureRow(id=target_id))
    audit_repo = FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
        )

    assert repo.deleted == []
    assert audit_repo.calls == []
    assert repo.session.commits == 0


@pytest.mark.asyncio
async def test_delete_raises_propagates_no_audit_no_commit():
    """Repo's delete blowing up means no audit row, no commit."""
    spec = top_level_spec()
    repo = FakeRepo()
    target_id = uuid4()
    repo.seed(FixtureRow, FixtureRow(id=target_id))
    repo.delete_raises = RuntimeError("db blew up")
    audit_repo = FakeAuditRepo()

    with pytest.raises(RuntimeError, match="db blew up"):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
        )

    assert audit_repo.calls == []
    assert repo.session.commits == 0


@pytest.mark.asyncio
async def test_no_audit_binding_raises_value_error():
    """Framework refuses to silently skip the audit row."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=None,
    )
    repo = FakeRepo()
    target_id = uuid4()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    with pytest.raises(ValueError, match="audit"):
        await handle_delete(
            spec,
            target_id=target_id,
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_no_write_authz_skips_auth_check():
    """Top-level entity with `write_authz=None` proceeds without an auth check."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(),
    )

    assert len(repo.deleted) == 1


# --- make_delete_handler factory ------------------------------------------


def test_make_delete_handler_top_level_signature():
    """Returned handler exposes the spec's id_param + repo/audit/user."""
    spec = top_level_spec()
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
    spec = child_spec()
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
    """Stack traces should be readable — handler `__name__` includes entity name."""
    spec = top_level_spec()
    handler = make_delete_handler(spec)
    assert handler.__name__ == "_handle_delete_widget"


# --- delete_forbid_self ---------------------------------------------------


@pytest.mark.asyncio
async def test_handle_delete_rejects_self_when_flag_set():
    """`delete_forbid_self=True` blocks the request with 403 if the URL
    target id equals the requesting user's id."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        routes=RouteSet(delete=True),
        delete_forbid_self=True,
    )
    actor_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=actor_id))
    audit_repo = FakeAuditRepo()
    actor = make_user(id_=actor_id, is_superuser=True)

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
    """The flag fires only on self-target — admins can still delete other users' rows."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        routes=RouteSet(delete=True),
        delete_forbid_self=True,
    )
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    await handle_delete(
        spec,
        target_id=target_id,
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=make_user(is_superuser=True),
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
            model=FixtureRow,
            audit=make_audit(),
            delete_forbid_self=True,
            routes=RouteSet(detail=True),
        )
