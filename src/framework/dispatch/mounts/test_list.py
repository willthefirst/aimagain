"""Tests for `handle_list` and `make_list_handler` in `mounts/list_.py`.

Moved from `src/framework/dispatch/test_handlers.py`.
"""

import inspect
from types import SimpleNamespace
from urllib.parse import parse_qsl
from uuid import uuid4

import pytest

from src.framework.dispatch.entity_spec import EntitySpec, QueryParam, RouteSet
from src.framework.dispatch.mounts.conftest import (
    FixtureRow,
    child_spec,
    make_audit,
    top_level_spec,
)
from src.framework.dispatch.mounts.list_ import handle_list, make_list_handler


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


# --- Happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_list_returns_items_under_url_collection():
    """The framework binds the list under `spec.url_collection`, not
    `spec.name` — the existing list templates read `{{ widgets }}` etc."""
    spec = top_level_spec()
    row_a = FixtureRow(id=uuid4())
    row_b = FixtureRow(id=uuid4())

    class _ListRepo:
        async def list_widgets(self, **_kwargs):
            return [row_a, row_b]

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )
    assert context["widgets"] == [row_a, row_b]
    assert context["current_user"] is None


@pytest.mark.asyncio
async def test_handle_list_echoes_filter_values_as_selected():
    """For each filter passed in, the context carries `selected_<name>`
    so the filter form can preselect the active value."""
    spec = top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            return []

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={"kind": "alpha", "state": None},
    )
    assert context["selected_kind"] == "alpha"
    assert context["selected_state"] is None
    # The raw dict is also injected so list templates with inline filter
    # sidebars can read all active values without unpacking selected_* vars.
    assert context["filter_values"] == {"kind": "alpha", "state": None}


@pytest.mark.asyncio
async def test_handle_list_threads_filter_values_into_repo_call():
    """The repo receives every `filter_values` entry as a kwarg."""
    spec = top_level_spec()
    captured: dict = {}

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.update(kwargs)
            return []

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={"kind": "beta"},
    )
    # `offset` + `limit` come from the pagination layer (`page=1`,
    # `per_page=DEFAULT_PAGE_SIZE=15`, asked-for-rows=`per_page + 1`).
    assert captured == {"kind": "beta", "offset": 0, "limit": 16}


@pytest.mark.asyncio
async def test_handle_list_extras_merges_into_context():
    """`extras` is post-fetch; its return dict layers over the base
    context (last-write-wins — same semantics as handle_detail)."""
    spec = top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **_):
            return ["a", "b"]

    async def extras(*, items, **_):
        return {"extra_count": len(items), "current_user": "overridden"}

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


# --- Viewer-flag + exclude-self auto-injection (handle_list) -------------


@pytest.mark.asyncio
async def test_handle_list_injects_can_admin_actions():
    """`can_admin_actions` is `is_admin(viewer)` on list pages (no
    `is_self` semantics — every row is some other entity)."""
    spec = top_level_spec()

    class _ListRepo:
        async def list_widgets(self, **_):
            return []

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
        model=FixtureRow,
        audit=make_audit(),
        routes=RouteSet(list=True),
        list_exclude_self=True,
    )
    captured: list[dict] = []

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.append(kwargs)
            return []

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

    # `offset` + `limit` come from the pagination layer (page 1 of 15).
    assert captured[0] == {"exclude_self": viewer, "offset": 0, "limit": 16}
    assert captured[1] == {"offset": 0, "limit": 16}


@pytest.mark.asyncio
async def test_handle_list_omits_exclude_self_when_spec_opts_out():
    """Without `list_exclude_self=True`, the repo call carries no
    `exclude_self` kwarg — existing entities are unaffected."""
    spec = top_level_spec()
    captured: list[dict] = []

    class _ListRepo:
        async def list_widgets(self, **kwargs):
            captured.append(kwargs)
            return []

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=SimpleNamespace(id=uuid4(), is_superuser=False),
        filter_values={"kind": "alpha"},
    )

    # `offset` + `limit` come from the pagination layer (page 1 of 15).
    assert captured[0] == {"kind": "alpha", "offset": 0, "limit": 16}
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
        model=FixtureRow,
        audit=make_audit(),
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

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_DefaultOnlyRepo(),
        requesting_user=None,
        filter_values={},
    )

    assert captured["model"] is FixtureRow
    assert captured["order_by"] == "ORDER_BY_SENTINEL"
    # `offset` + `limit` come from the pagination layer (page 1 of 15).
    assert captured["kwargs"] == {"offset": 0, "limit": 16}


@pytest.mark.asyncio
async def test_handle_list_fallback_raises_when_no_order_by():
    """No bespoke list method AND no `list_order_by` is a misconfiguration.
    The framework can't pick an ordering for the caller, so it raises a
    clear error instead of executing a random-order list."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        routes=RouteSet(list=True),
    )

    class _DefaultOnlyRepo:
        async def list_default(self, model, *, order_by, **kwargs):  # pragma: no cover
            return []

    with pytest.raises(ValueError, match="list_order_by"):
        await handle_list(
            spec,
            request=_request_stub(),
            repo=_DefaultOnlyRepo(),
            requesting_user=None,
            filter_values={},
        )


# --- static_context (list) -----------------------------------------------


@pytest.mark.asyncio
async def test_handle_list_merges_static_context():
    """`spec.static_context` entries land in the list context, after the
    base context and `selected_<filter>` echoes."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        static_context={"widget_kinds": ("alpha", "beta")},
    )

    class _ListRepo:
        async def list_widgets(self, **_):
            return []

    context = await handle_list(
        spec,
        request=_request_stub(),
        repo=_ListRepo(),
        requesting_user=None,
        filter_values={},
    )

    assert context["widget_kinds"] == ("alpha", "beta")


# --- make_list_handler factory --------------------------------------------


def test_make_list_handler_signature_includes_filters_and_repos():
    """The factory must synthesize a typed signature so mount_list's
    introspection wires the filter query params and the typed repos."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
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


# --- Parent-owned list (subentity) ----------------------------------------


@pytest.mark.asyncio
async def test_handle_list_parent_owned_threads_parent_id_into_bespoke_method():
    """For a parent-owned spec, ``handle_list`` threads ``parent_id`` into
    the bespoke ``list_<collection>(**kwargs)`` call under the parent's
    ``id_param``. The bespoke method owns the actual scoping query."""
    spec = child_spec()
    parent_uuid = uuid4()
    captured: dict = {}

    class _Repo:
        async def list_widget_parts(self, **kwargs):
            captured["kwargs"] = kwargs
            return []

    await handle_list(
        spec,
        request=_request_stub(),
        repo=_Repo(),
        requesting_user=None,
        filter_values={},
        parent_id=parent_uuid,
    )

    # Parent's id_param key lands in kwargs alongside the pagination kwargs.
    assert captured["kwargs"]["parent_id"] == parent_uuid
    assert captured["kwargs"]["offset"] == 0
    assert captured["kwargs"]["limit"] == 16


@pytest.mark.asyncio
async def test_handle_list_parent_owned_without_bespoke_method_raises():
    """A parent-owned spec without a bespoke ``list_<collection>`` method
    can't fall through to ``list_default`` — that method has no concept
    of parent-id scoping and would silently return ALL rows across all
    parents. Surface the misconfig at request time."""
    spec = child_spec()

    class _DefaultOnlyRepo:
        async def list_default(self, *args, **kwargs):  # pragma: no cover
            return []

    with pytest.raises(ValueError, match="list_widget_parts"):
        await handle_list(
            spec,
            request=_request_stub(),
            repo=_DefaultOnlyRepo(),
            requesting_user=None,
            filter_values={},
            parent_id=uuid4(),
        )


def test_make_list_handler_signature_includes_parent_id_for_parent_owned_spec():
    """``include_parent_id`` is on ``_LIST_SHAPE`` — the synthesized
    handler binds ``<parent>_id`` as a path param so FastAPI dependency
    injection forwards the URL segment into the call."""
    spec = child_spec()
    handler = make_list_handler(spec)
    names = list(inspect.signature(handler).parameters)
    assert "parent_id" in names  # parent spec uses id_param="parent_id"
