"""Tests for `src/api/common/responses.py` helpers."""

import json
import uuid

from .responses import (
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)


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
