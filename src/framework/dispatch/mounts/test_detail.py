"""Tests for `handle_detail` and `make_detail_handler` in `mounts/detail.py`.

Moved from `src/framework/dispatch/test_handlers.py`.
"""

import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.mounts.conftest import (
    FakeRepo,
    FixtureRow,
    make_audit,
    make_user,
    top_level_spec,
)
from src.framework.dispatch.mounts.detail import handle_detail, make_detail_handler
from src.framework.http.exceptions import NotFoundError


def _request_stub():
    from urllib.parse import parse_qsl

    return SimpleNamespace(
        query_params=SimpleNamespace(get=dict(parse_qsl("")).get),
        url=SimpleNamespace(query=""),
    )


def _can_edit_for_owner(obj, user) -> bool:
    """Stand-in for `is_owner_or_admin` — predicate form of write_authz."""
    return user is not None and getattr(obj, "owner_id", None) == user.id


def _is_self_or_admin(actor, target) -> bool:
    """Stand-in `private_field_predicate`: viewer is self or admin."""
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    subject_id = getattr(target, "owner_id", None) or getattr(target, "id", None)
    return getattr(actor, "id", None) == subject_id


# --- Happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_top_level_happy_path():
    """No can_write, no extras: load target, bind under spec.name."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)
    user = make_user()

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
        model=FixtureRow,
        can_write=_can_edit_for_owner,
        audit=make_audit(),
    )
    target_id = uuid4()
    owner_id = uuid4()
    owner = make_user(id_=owner_id)
    stranger = make_user()

    target = FixtureRow(id=target_id)
    target.owner_id = owner_id  # type: ignore[attr-defined]
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        requesting_user=make_user(),
        extras=extras,
    )

    assert context["extra_flag"] is True
    assert context["widget"] == "projection"  # last-write-wins


@pytest.mark.asyncio
async def test_detail_extras_receives_extra_kwargs():
    """`extra_kwargs` is forwarded to the extras callable, in addition to
    `target` / `request` / `requesting_user`."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)
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
        requesting_user=make_user(),
        extras=extras,
        extra_kwargs={"side_repo": side_repo},
    )

    assert captured["target"] is target
    assert captured["side_repo"] is side_repo


@pytest.mark.asyncio
async def test_detail_target_not_found_raises_not_found():
    spec = top_level_spec()
    repo = FakeRepo()
    with pytest.raises(NotFoundError):
        await handle_detail(
            spec,
            request=_request_stub(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_detail_anonymous_viewer_supported():
    """`requesting_user=None` works — public-detail entities (no
    read_user_dep) can pass None."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=None,
    )

    assert context["current_user"] is None


# --- make_detail_handler factory ------------------------------------------


def test_make_detail_handler_signature():
    spec = top_level_spec(write_authz=None)
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

    spec = top_level_spec(write_authz=None)
    handler = make_detail_handler(spec, extra_repos=(("side_repo", _SideRepo),))
    sig = inspect.signature(handler)
    assert "side_repo" in sig.parameters
    assert sig.parameters["side_repo"].annotation is _SideRepo


def test_make_detail_handler_name_includes_entity():
    spec = top_level_spec(write_authz=None)
    handler = make_detail_handler(spec)
    assert handler.__name__ == "_handle_get_widget_detail"


@pytest.mark.asyncio
async def test_make_detail_handler_delegates_to_handle_detail():
    """The factory-built handler invokes `handle_detail` with the spec
    bound and `extra_repos` forwarded into `extra_kwargs`."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        requesting_user=make_user(),
        side_repo=side_repo,
    )

    assert context["widget"] is target
    assert context["extra_flag"] is True
    assert captured["side_repo"] is side_repo


# --- Viewer-flag + projection auto-injection (handle_detail) -------------


@pytest.mark.asyncio
async def test_detail_injects_is_self_for_owned_resource():
    """`is_self` compares `target.<owner_attr>` to viewer.id when
    `spec.owner_attr` is set (the owned-resource rule)."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        owner_attr="owner_id",
        audit=make_audit(),
    )
    target_id = uuid4()
    owner_id = uuid4()
    target = FixtureRow(id=target_id)
    target.owner_id = owner_id  # type: ignore[attr-defined]
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        model=FixtureRow,
        owner_attr=None,
        audit=make_audit(),
    )
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        model=FixtureRow,
        owner_attr=None,
        audit=make_audit(),
    )
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        model=FixtureRow,
        private_fields=("secret",),
        private_field_predicate=_is_self_or_admin,
        audit=make_audit(),
    )
    spec_without = top_level_spec()  # no private_field_predicate
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
        model=FixtureRow,
        public_fields=("id",),
        private_fields=("parent_id",),
        private_field_predicate=_is_self_or_admin,
        audit=make_audit(),
    )
    target_id = uuid4()
    parent_id = uuid4()
    target = FixtureRow(id=target_id, parent_id=parent_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)

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
    spec = top_level_spec()
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=False),
    )

    assert "target_widget" not in context


# --- static_context (detail) ---------------------------------------------


@pytest.mark.asyncio
async def test_handle_detail_merges_static_context():
    """`spec.static_context` entries land in the detail context, after
    auto-injected viewer keys and before extras run."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        static_context={"widget_kinds": ("alpha", "beta")},
    )
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=make_user(),
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
        model=FixtureRow,
        audit=make_audit(),
        static_context={"flag": "from-static"},
    )
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))

    async def extras(**_):
        return {"flag": "from-extras"}

    context = await handle_detail(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=make_user(),
        extras=extras,
    )

    assert context["flag"] == "from-extras"


def test_static_context_default_is_empty_dict():
    """Default is empty; absent declaration means no extra keys land."""
    spec = top_level_spec()
    assert spec.static_context == {}


# --- Spec construction-time validation -----------------------------------


def test_public_fields_without_predicate_rejected():
    """Declaring `public_fields` without a `private_field_predicate`
    would let the projection silently pass every private field."""
    with pytest.raises(ValueError, match="private_field_predicate"):
        EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=FixtureRow,
            public_fields=("id",),
            audit=make_audit(),
        )


def test_list_exclude_self_requires_list_route():
    """`list_exclude_self` is only consumed by handle_list — without a
    list route the flag would be dead."""
    with pytest.raises(ValueError, match="routes.list"):
        EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=FixtureRow,
            audit=make_audit(),
            list_exclude_self=True,
            routes=RouteSet(detail=True),
        )
