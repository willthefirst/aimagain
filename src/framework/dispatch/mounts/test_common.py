"""Tests for shared mount helpers in `_common.py`.

`subresource_breadcrumb_items` is the single producer of the 3-step
`_breadcrumb_items` injected by both `mount_related_list` and
`mount_edge_routes` — same tuple shape, same lock-reason wiring, one
test target.
"""

from __future__ import annotations

from unittest.mock import patch

from src.domain.logic import capabilities
from src.framework.dispatch.mounts._common import subresource_breadcrumb_items


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
