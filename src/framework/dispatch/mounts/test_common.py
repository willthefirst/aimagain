"""Tests for shared mount helpers in `_common.py`.

`subresource_breadcrumb_items` is the single producer of the 3-step
`_breadcrumb_items` injected by both `mount_related_list` and
`mount_edge_routes` — same tuple shape, same lock-reason wiring, one
test target. `ParentBreadcrumbPlumbing` is the single handshake that
wires that producer into each per-verb mount (`mount_list`,
`mount_form`, `mount_related_list`) — so the mount-time + request-time
glue lives in one place too.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.logic import capabilities
from src.framework.dispatch.mounts._common import (
    ParentBreadcrumbPlumbing,
    subresource_breadcrumb_items,
)


class _Spec:
    """Minimal stand-in for EntitySpec — the helper reads `name`,
    `url_collection`, and `display_label_fn`. Avoids importing the real
    spec dataclass into a unit test."""

    def __init__(self, name: str, url_collection: str, label_fn):
        self.name = name
        self.url_collection = url_collection
        self.display_label_fn = label_fn


def _user_spec() -> _Spec:
    return _Spec("user", "users", lambda u: u.username)


class _User:
    def __init__(self, username: str = "alice"):
        self.username = username


def test_emits_three_tuple_chain_with_collection_parent_child_shape():
    """Items are (label, href|None, lock_reason|None) tuples in chain order."""
    spec = _user_spec()
    parent = _User("alice")
    with patch(
        "src.framework.rendering.route_urls.entity_lock_reason", return_value=None
    ):
        items = subresource_breadcrumb_items(
            parent_spec=spec,
            parent_row=parent,
            parent_path="/users/me",
            child_label="Favorites",
            viewer=parent,
        )
    assert items == [
        ("Users", "/users", None),
        ("alice", "/users/me", None),
        ("Favorites", None, None),
    ]


def test_collection_tuple_carries_lock_reason_when_viewer_locked_out():
    """When `entity_lock_reason` returns a `REASON_*` code, it lands on
    the first tuple's third element — the breadcrumb macro renders the
    collection back-link as a locked popover trigger."""
    spec = _user_spec()
    parent = _User("alice")
    with patch(
        "src.framework.rendering.route_urls.entity_lock_reason",
        return_value=capabilities.REASON_NOT_A_VERIFIED_PROVIDER,
    ):
        items = subresource_breadcrumb_items(
            parent_spec=spec,
            parent_row=parent,
            parent_path="/users/me",
            child_label="Favorites",
            viewer=parent,
        )
    assert items[0] == ("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER)
    # Parent-row and child segments are never locked here — only the
    # collection back-target can fail the read policy.
    assert items[1][2] is None
    assert items[2][2] is None


def test_parent_label_comes_from_spec_display_label_fn():
    """The parent-row label flows through `display_label_fn(parent_row)`
    — so renames live in one place (the spec) rather than each mount
    site's tuple literal."""
    spec = _Spec("clinician", "clinicians", lambda c: f"{c.first} {c.last}")

    class _C:
        first = "Dr"
        last = "Doe"

    with patch(
        "src.framework.rendering.route_urls.entity_lock_reason", return_value=None
    ):
        items = subresource_breadcrumb_items(
            parent_spec=spec,
            parent_row=_C(),
            parent_path="/clinicians/abc",
            child_label="Openings",
            viewer=None,
        )
    assert items[1] == ("Dr Doe", "/clinicians/abc", None)


def test_asserts_when_parent_spec_lacks_display_label_fn():
    """Callers gate on `display_label_fn is not None` before invoking —
    a `None` here is a programmer error, not a runtime branch."""
    spec = _Spec("nameless", "nameless", None)
    import pytest

    with pytest.raises(AssertionError, match="display_label_fn"):
        subresource_breadcrumb_items(
            parent_spec=spec,
            parent_row=object(),
            parent_path="/nameless/1",
            child_label="Child",
            viewer=None,
        )


# --- ParentBreadcrumbPlumbing -------------------------------------------


class _ParentEntitySpec:
    """Stand-in EntitySpec — `ParentBreadcrumbPlumbing` reads `name`,
    `url_collection`, `model`, and `display_label_fn`. The real
    EntitySpec has dozens of fields we don't need."""

    def __init__(self, *, label_fn, model=object):
        self.name = "clinician"
        self.url_collection = "clinicians"
        self.display_label_fn = label_fn
        self.model = model


class _ParentResourceSpec:
    """Stand-in ResourceSpec. Holds the `entity_spec` back-reference
    that `to_resource_spec()` sets on the real ResourceSpec, plus the
    `id_param` and `repo_dep` the plumbing reads."""

    def __init__(self, *, entity_spec, repo_dep=lambda: None):
        self.entity_spec = entity_spec
        self.id_param = "clinician_id"
        self.repo_dep = repo_dep


class _ChildResourceSpec:
    def __init__(self, *, parent):
        self.parent = parent


def _parent_es(*, label_fn=lambda c: c.name, model=object) -> _ParentEntitySpec:
    return _ParentEntitySpec(label_fn=label_fn, model=model)


def test_plumbing_inactive_for_top_level_spec():
    """Top-level (parent=None) specs skip the breadcrumb path —
    `extra_static_deps` is empty and `inject` is a no-op."""
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(_ChildResourceSpec(parent=None))
    assert plumbing.active is False
    assert plumbing.extra_static_deps == ()


def test_plumbing_inactive_when_parent_lacks_display_label_fn():
    """The opt-in gate is `parent.entity_spec.display_label_fn`. Without
    it, the mount can't produce a parent-row label, so the plumbing
    falls back to the single-segment chrome breadcrumb instead of
    injecting a half-built chain."""
    parent_rs = _ParentResourceSpec(entity_spec=_parent_es(label_fn=None))
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(
        _ChildResourceSpec(parent=parent_rs)
    )
    assert plumbing.active is False
    assert plumbing.extra_static_deps == ()


def test_plumbing_active_when_parent_has_display_label_fn():
    """When the parent declares `display_label_fn`, the plumbing exposes
    a `__parent_repo__` Depends pair so the synthesis layer wires the
    parent's repo into the route's kwargs."""
    repo_dep = lambda: "<repo-dep-sentinel>"  # noqa: E731
    parent_rs = _ParentResourceSpec(
        entity_spec=_parent_es(label_fn=lambda c: c.name),
        repo_dep=repo_dep,
    )
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(
        _ChildResourceSpec(parent=parent_rs)
    )
    assert plumbing.active is True
    assert plumbing.extra_static_deps == (("__parent_repo__", repo_dep),)


def test_plumbing_for_parent_spec_uses_passed_parent_directly():
    """`mount_related_list` takes the parent spec as a function arg
    (not via `child_spec.parent`) because the same child entity can be
    related-listed under different parents — verify both constructors
    end up with the same plumbing state for the same parent."""
    parent_rs = _ParentResourceSpec(entity_spec=_parent_es())
    via_parent = ParentBreadcrumbPlumbing.for_parent_spec(parent_rs)
    via_child = ParentBreadcrumbPlumbing.for_child_spec(
        _ChildResourceSpec(parent=parent_rs)
    )
    assert via_parent.active == via_child.active
    assert via_parent.extra_static_deps == via_child.extra_static_deps


class _FakeParentRepo:
    def __init__(self, row):
        self._row = row
        self.calls: list[tuple] = []

    async def get_by_model_id(self, model, obj_id):
        self.calls.append((model, obj_id))
        return self._row


@pytest.mark.asyncio
async def test_inject_writes_breadcrumb_items_into_context():
    """Active plumbing fetches the parent row, builds the chain via
    `subresource_breadcrumb_items`, and assigns it to
    `context['_breadcrumb_items']`."""
    parent_id = uuid4()
    parent_row = SimpleNamespace(id=parent_id, name="Dr Doe")
    repo = _FakeParentRepo(parent_row)
    parent_rs = _ParentResourceSpec(
        entity_spec=_parent_es(label_fn=lambda c: c.name, model=SimpleNamespace),
    )
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(
        _ChildResourceSpec(parent=parent_rs)
    )
    context: dict = {}
    with patch(
        "src.framework.rendering.route_urls.entity_lock_reason", return_value=None
    ):
        await plumbing.inject(
            context=context,
            kwargs={
                "clinician_id": parent_id,
                "__parent_repo__": repo,
                "requesting_user": None,
            },
            child_label="Practices",
        )
    assert repo.calls == [(SimpleNamespace, parent_id)]
    assert context["_breadcrumb_items"] == [
        ("Clinicians", "/clinicians", None),
        ("Dr Doe", f"/clinicians/{parent_id}", None),
        ("Practices", None, None),
    ]


@pytest.mark.asyncio
async def test_inject_no_op_when_inactive():
    """Top-level / opt-out specs leave the context untouched — no
    `_breadcrumb_items` key, so the chrome falls through to its
    single-segment default."""
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(_ChildResourceSpec(parent=None))
    context: dict = {}
    await plumbing.inject(context=context, kwargs={}, child_label="anything")
    assert context == {}


@pytest.mark.asyncio
async def test_inject_no_op_when_parent_row_missing():
    """A 404 on the parent fetch is best-effort — the route's own
    handler owns the user-facing 404; the breadcrumb just stays absent
    rather than crashing the page render."""
    parent_rs = _ParentResourceSpec(entity_spec=_parent_es())
    plumbing = ParentBreadcrumbPlumbing.for_child_spec(
        _ChildResourceSpec(parent=parent_rs)
    )
    context: dict = {}
    await plumbing.inject(
        context=context,
        kwargs={
            "clinician_id": uuid4(),
            "__parent_repo__": _FakeParentRepo(None),
            "requesting_user": None,
        },
        child_label="Practices",
    )
    assert "_breadcrumb_items" not in context


def test_parent_path_is_used_verbatim_for_singleton_alias_paths():
    """`mount_edge_routes` passes `/users/me` (singleton alias); the
    helper preserves it without rebuilding from id. Verifies the path
    isn't recomputed from `parent_row.id`."""
    spec = _user_spec()
    parent = _User("alice")
    with patch(
        "src.framework.rendering.route_urls.entity_lock_reason", return_value=None
    ):
        items = subresource_breadcrumb_items(
            parent_spec=spec,
            parent_row=parent,
            parent_path="/users/me",  # singleton alias, not a UUID
            child_label="Favorites",
            viewer=parent,
        )
    assert items[1][1] == "/users/me"
