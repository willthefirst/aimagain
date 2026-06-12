"""Tests for `src/framework/authz.py`."""

import uuid
from types import SimpleNamespace

import pytest

from src.framework.access.authz.authz import (
    assert_owner_or_admin,
    assert_self_or_admin,
    is_admin,
    is_owner,
    is_owner_or_admin,
    is_self_or_admin,
    list_picker_options_for,
    make_fk_ownership_payload_authz,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError


def _user(*, is_superuser: bool = False, id_=None):
    return SimpleNamespace(id=id_ or uuid.uuid4(), is_superuser=is_superuser)


# --- is_admin --------------------------------------------------------------


def test_is_admin_none_user():
    assert is_admin(None) is False


def test_is_admin_regular_user():
    assert is_admin(_user()) is False


def test_is_admin_superuser():
    assert is_admin(_user(is_superuser=True)) is True


# --- is_owner --------------------------------------------------------------


def test_is_owner_none_user():
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, None) is False


def test_is_owner_matches_owner_id():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert is_owner(obj, u) is True


def test_is_owner_non_matching_id():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, u) is False


def test_is_owner_admin_is_not_automatic_owner():
    """`is_owner` checks ownership only; admin-override is the
    `is_owner_or_admin` composition's job, not `is_owner`'s."""
    u = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, u) is False


def test_is_owner_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert is_owner(obj, u, owner_attr="user_id") is True


# --- is_owner_or_admin -----------------------------------------------------


def test_is_owner_or_admin_none_user():
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, None) is False


def test_is_owner_or_admin_owner_passes():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert is_owner_or_admin(obj, u) is True


def test_is_owner_or_admin_admin_passes_even_if_not_owner():
    admin = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, admin) is True


def test_is_owner_or_admin_stranger_fails():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, u) is False


def test_is_owner_or_admin_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert is_owner_or_admin(obj, u, owner_attr="user_id") is True


# --- is_self_or_admin ------------------------------------------------------


def test_is_self_or_admin_none_actor():
    target = _user()
    assert is_self_or_admin(None, target) is False


def test_is_self_or_admin_self():
    u = _user()
    assert is_self_or_admin(u, u) is True


def test_is_self_or_admin_admin_other():
    admin = _user(is_superuser=True)
    target = _user()
    assert is_self_or_admin(admin, target) is True


def test_is_self_or_admin_stranger():
    actor = _user()
    target = _user()
    assert is_self_or_admin(actor, target) is False


# --- assert_owner_or_admin (composes is_owner + is_admin) ------------------


def test_owner_passes():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert_owner_or_admin(obj, u)


def test_superuser_passes_even_if_not_owner():
    u = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert_owner_or_admin(obj, u)


def test_non_owner_non_admin_raises():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    with pytest.raises(ForbiddenError) as excinfo:
        assert_owner_or_admin(obj, u, action="edit this resource")
    assert "Only the owner or an admin can edit this resource" in str(
        excinfo.value.detail
    )


def test_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert_owner_or_admin(obj, u, owner_attr="user_id")


def test_custom_action_in_message():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    with pytest.raises(ForbiddenError) as excinfo:
        assert_owner_or_admin(obj, u, action="delete this widget")
    assert "delete this widget" in str(excinfo.value.detail)


# --- assert_self_or_admin (composes is_self_or_admin) ----------------------


def test_assert_self_passes():
    u = _user()
    assert_self_or_admin(u, u)


def test_assert_admin_passes_even_if_not_self():
    admin = _user(is_superuser=True)
    target = _user()
    assert_self_or_admin(target, admin)


def test_assert_stranger_raises():
    actor = _user()
    target = _user()
    with pytest.raises(ForbiddenError) as excinfo:
        assert_self_or_admin(target, actor, action="view this profile")
    assert "Only the user themselves or an admin can view this profile" in str(
        excinfo.value.detail
    )


# --- list_picker_options_for ----------------------------------------------
#
# Composes `list_visible_to` (already pinned through per-entity integration
# tests) with the re-include-attached rule. The unit tests below only need
# to lock the re-include branching since the visible-set call is straight
# delegation.


class _StubRepo:
    """In-memory stand-in for a repository — minimum surface needed by
    `list_picker_options_for`: `list_for_user`, `list_default`, and
    `get_by_model_id`."""

    def __init__(self, *, owned, all_, by_id=None):
        self._owned = list(owned)
        self._all = list(all_)
        self._by_id = by_id or {}

    async def list_for_user(self, _user_id):
        return list(self._owned)

    async def list_default(self, _model, order_by=None):
        return list(self._all)

    async def get_by_model_id(self, _model, id_):
        return self._by_id.get(id_)


class _StubModel:
    """Stand-in for a SQLAlchemy model class — `list_visible_to` reads
    `model.created_at.desc()` for the superuser path."""

    created_at = SimpleNamespace(desc=lambda: None)


def _row(*, id_):
    return SimpleNamespace(id=id_)


@pytest.mark.asyncio
async def test_list_picker_options_for_no_attached_returns_visible_set():
    """When `attached_id=None` (create form, or edit form whose row's
    FK *is* in the visible set), the helper is a straight pass-through
    over `list_visible_to`."""
    user = _user()
    a, b = _row(id_=uuid.uuid4()), _row(id_=uuid.uuid4())
    repo = _StubRepo(owned=[a, b], all_=[a, b])
    out = await list_picker_options_for(repo, user, _StubModel)
    assert out == [a, b]


@pytest.mark.asyncio
async def test_list_picker_options_for_appends_attached_when_unowned():
    """Edit-form's attached row that the requesting user no longer owns
    still appears in the picker — otherwise the rendered `<select>`
    would silently drop the FK on submit. Re-fetched from the repo and
    appended; `assert_fk_ownership` still gates whether the user may
    *change* the FK."""
    user = _user()
    visible = _row(id_=uuid.uuid4())
    orphan_id = uuid.uuid4()
    orphan = _row(id_=orphan_id)
    repo = _StubRepo(owned=[visible], all_=[], by_id={orphan_id: orphan})
    out = await list_picker_options_for(repo, user, _StubModel, attached_id=orphan_id)
    assert out == [visible, orphan]


@pytest.mark.asyncio
async def test_list_picker_options_for_no_duplicate_when_attached_is_owned():
    """When the attached row is already in the visible set, the helper
    returns the visible list unchanged — no duplicate entry."""
    user = _user()
    owned_id = uuid.uuid4()
    owned = _row(id_=owned_id)
    repo = _StubRepo(owned=[owned], all_=[])
    out = await list_picker_options_for(repo, user, _StubModel, attached_id=owned_id)
    assert out == [owned]


@pytest.mark.asyncio
async def test_list_picker_options_for_attached_missing_returns_visible_set():
    """When the attached row id no longer resolves (deleted parent),
    don't surface a None — return the visible set as-is. The downstream
    form will render without the now-deleted FK, which is the right UX
    for an orphaned attachment."""
    user = _user()
    visible = _row(id_=uuid.uuid4())
    repo = _StubRepo(owned=[visible], all_=[], by_id={})
    out = await list_picker_options_for(
        repo, user, _StubModel, attached_id=uuid.uuid4()
    )
    assert out == [visible]


@pytest.mark.asyncio
async def test_list_picker_options_for_superuser_sees_all():
    """Superusers get the full set (the visible-set branch reads
    `list_default`, not `list_for_user`)."""
    admin = _user(is_superuser=True)
    a, b = _row(id_=uuid.uuid4()), _row(id_=uuid.uuid4())
    repo = _StubRepo(owned=[], all_=[a, b])
    out = await list_picker_options_for(repo, admin, _StubModel)
    assert out == [a, b]


# --- make_fk_ownership_payload_authz --------------------------------------
#
# The factory closes over (attr, parent_model, parent_noun, child_noun,
# parent_repo_kwarg) and produces a callable that matches the framework's
# `payload_authz` contract. Each per-entity wrapper that used to be a
# hand-written `async def` becomes a one-line factory call.


class _StubParentModel:
    pass


@pytest.mark.asyncio
async def test_make_fk_ownership_payload_authz_owner_passes():
    """Happy path: payload's FK points at a parent the requesting user
    owns. No exception."""
    user = _user()
    parent_id = uuid.uuid4()
    parent = SimpleNamespace(id=parent_id, owner_id=user.id)
    repo = _StubRepo(owned=[], all_=[], by_id={parent_id: parent})
    hook = make_fk_ownership_payload_authz(
        attr="parent_id",
        parent_model=_StubParentModel,
        parent_noun="Parent",
        child_noun="Child",
        parent_repo_kwarg="parent_repo",
    )
    await hook(
        payload=SimpleNamespace(parent_id=parent_id),
        requesting_user=user,
        parent_repo=repo,
    )


@pytest.mark.asyncio
async def test_make_fk_ownership_payload_authz_unowned_403():
    """403 when the parent exists but belongs to someone else."""
    user = _user()
    parent_id = uuid.uuid4()
    parent = SimpleNamespace(id=parent_id, owner_id=uuid.uuid4())
    repo = _StubRepo(owned=[], all_=[], by_id={parent_id: parent})
    hook = make_fk_ownership_payload_authz(
        attr="parent_id",
        parent_model=_StubParentModel,
        parent_noun="Parent",
        child_noun="Child",
        parent_repo_kwarg="parent_repo",
    )
    with pytest.raises(ForbiddenError):
        await hook(
            payload=SimpleNamespace(parent_id=parent_id),
            requesting_user=user,
            parent_repo=repo,
        )


@pytest.mark.asyncio
async def test_make_fk_ownership_payload_authz_missing_404():
    """404 when the parent doesn't exist — same shape as
    `assert_fk_ownership` (no info leak about other users' parent ids)."""
    user = _user()
    parent_id = uuid.uuid4()
    repo = _StubRepo(owned=[], all_=[], by_id={})
    hook = make_fk_ownership_payload_authz(
        attr="parent_id",
        parent_model=_StubParentModel,
        parent_noun="Parent",
        child_noun="Child",
        parent_repo_kwarg="parent_repo",
    )
    with pytest.raises(NotFoundError):
        await hook(
            payload=SimpleNamespace(parent_id=parent_id),
            requesting_user=user,
            parent_repo=repo,
        )


@pytest.mark.asyncio
async def test_make_fk_ownership_payload_authz_none_fk_noop():
    """PATCH payloads where the FK is absent / None are a no-op —
    same delegation contract as `assert_fk_ownership`."""
    user = _user()
    repo = _StubRepo(owned=[], all_=[], by_id={})
    hook = make_fk_ownership_payload_authz(
        attr="parent_id",
        parent_model=_StubParentModel,
        parent_noun="Parent",
        child_noun="Child",
        parent_repo_kwarg="parent_repo",
    )
    await hook(
        payload=SimpleNamespace(parent_id=None),
        requesting_user=user,
        parent_repo=repo,
    )


@pytest.mark.asyncio
async def test_make_fk_ownership_payload_authz_superuser_bypass():
    """Superusers bypass the owner check (the rule the underlying
    `assert_fk_ownership` enforces)."""
    admin = _user(is_superuser=True)
    parent_id = uuid.uuid4()
    parent = SimpleNamespace(id=parent_id, owner_id=uuid.uuid4())
    repo = _StubRepo(owned=[], all_=[], by_id={parent_id: parent})
    hook = make_fk_ownership_payload_authz(
        attr="parent_id",
        parent_model=_StubParentModel,
        parent_noun="Parent",
        child_noun="Child",
        parent_repo_kwarg="parent_repo",
    )
    await hook(
        payload=SimpleNamespace(parent_id=parent_id),
        requesting_user=admin,
        parent_repo=repo,
    )
