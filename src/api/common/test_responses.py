"""Tests for `src/api/common/responses.py` helpers."""

import json
import uuid
from types import SimpleNamespace

import pytest

from .responses import (
    base_context,
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)

# --- base_context: chrome scalars ----------------------------------------


def test_base_context_anonymous():
    ctx = base_context(None)
    assert ctx == {
        "is_authenticated": False,
        "is_admin": False,
        "current_username": None,
        "current_user_id": None,
    }


def test_base_context_regular_user():
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id, username="alice", is_superuser=False)
    assert base_context(user) == {
        "is_authenticated": True,
        "is_admin": False,
        "current_username": "alice",
        "current_user_id": user_id,
    }


def test_base_context_admin():
    user = SimpleNamespace(id=uuid.uuid4(), username="root", is_superuser=True)
    ctx = base_context(user)
    assert ctx["is_admin"] is True
    assert ctx["is_authenticated"] is True


# --- existing helpers ----------------------------------------------------


def test_created_response_defaults_hx_redirect_to_location():
    obj_id = uuid.uuid4()
    resp = created_response(id=obj_id, location=f"/posts/{obj_id}")
    assert resp.status_code == 201
    assert json.loads(resp.body) == {"id": str(obj_id)}
    assert resp.headers["Location"] == f"/posts/{obj_id}"
    assert resp.headers["HX-Redirect"] == f"/posts/{obj_id}"


def test_created_response_separate_location_and_hx_redirect():
    obj_id = uuid.uuid4()
    resp = created_response(
        id=obj_id,
        location=f"/providers/{obj_id}",
        hx_redirect=f"/providers/{obj_id}/form",
    )
    assert resp.headers["Location"] == f"/providers/{obj_id}"
    assert resp.headers["HX-Redirect"] == f"/providers/{obj_id}/form"


def test_updated_response_with_body():
    resp = updated_response(body={"id": "abc", "name": "x"}, hx_redirect="/x")
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"id": "abc", "name": "x"}
    assert resp.headers["HX-Redirect"] == "/x"


def test_updated_response_empty_body_default():
    resp = updated_response(hx_redirect="/x")
    assert resp.status_code == 200
    assert json.loads(resp.body) == {}


def test_deleted_response_204_with_hx_redirect():
    resp = deleted_response(hx_redirect="/posts")
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/posts"


def test_refreshed_response_204_with_hx_refresh():
    resp = refreshed_response()
    assert resp.status_code == 200
    assert resp.headers["HX-Refresh"] == "true"


def test_updated_response_hx_refresh_sets_header_with_body():
    """`hx_refresh=True` swaps the HX-Redirect header for HX-Refresh while
    keeping the optional body — the shape state-axis subresources need."""
    resp = updated_response(body={"id": "u1", "is_active": False}, hx_refresh=True)
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"id": "u1", "is_active": False}
    assert resp.headers["HX-Refresh"] == "true"
    assert "HX-Redirect" not in resp.headers


def test_updated_response_requires_one_of_redirect_or_refresh():
    with pytest.raises(ValueError, match="hx_redirect or hx_refresh"):
        updated_response(body={"x": 1})


def test_updated_response_rejects_both_redirect_and_refresh():
    with pytest.raises(ValueError, match="hx_redirect or hx_refresh"):
        updated_response(hx_redirect="/x", hx_refresh=True)
