"""Tests for `src/api/common/resource_routes.py`.

Mounts a tiny stub resource against a FastAPI app and exercises the
mount functions end-to-end. Validates that:
  - Path params use the per-resource `id_param` name from the spec.
  - Handlers receive `repo`, `audit_repo`, `requesting_user`, and the
    resource id under its declared kwarg name.
  - Response shape (status, HX-Redirect) matches the hand-written
    equivalents.
  - Misconfigurations (missing `write_user_dep`, sub-resource specs
    until slice 8) raise at mount time, not at request time.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api.common.resource_routes import ResourceSpec, mount_delete


def _build_app(spec: ResourceSpec, captured: dict) -> FastAPI:
    """Mount `mount_delete` for `spec` and capture every handler call into
    `captured`. Stub deps return predictable sentinels so kwargs are
    inspectable in assertions."""

    async def delete_handler(**kwargs):
        captured.update(kwargs)

    app = FastAPI()
    router = APIRouter(prefix=f"/{spec.collection}")
    mount_delete(
        router,
        spec,
        handler=delete_handler,
        audit_repo_dep=lambda: SimpleNamespace(name="audit_repo"),
    )
    app.include_router(router)
    return app


def test_mount_delete_returns_204_with_hx_redirect_default():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    captured: dict = {}
    client = TestClient(_build_app(spec, captured))

    widget_id = uuid4()
    resp = client.delete(f"/widgets/{widget_id}")

    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/widgets"


def test_mount_delete_passes_id_under_spec_kwarg_name():
    spec = ResourceSpec(
        collection="gadgets",
        id_param="gadget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    captured: dict = {}
    client = TestClient(_build_app(spec, captured))

    gadget_id = uuid4()
    resp = client.delete(f"/gadgets/{gadget_id}")

    assert resp.status_code == 204
    assert "gadget_id" in captured
    assert str(captured["gadget_id"]) == str(gadget_id)
    assert captured["repo"].name == "repo"
    assert captured["audit_repo"].name == "audit_repo"


def test_mount_delete_uses_custom_redirect_callable():
    def custom_redirect(*, sprocket_id):
        return f"/sprockets-overview?last={sprocket_id}"

    spec = ResourceSpec(
        collection="sprockets",
        id_param="sprocket_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
        delete_redirect=custom_redirect,
    )
    captured: dict = {}
    client = TestClient(_build_app(spec, captured))

    sprocket_id = uuid4()
    resp = client.delete(f"/sprockets/{sprocket_id}")

    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == f"/sprockets-overview?last={sprocket_id}"


def test_mount_delete_rejects_subresource_spec_until_slice_8():
    parent = ResourceSpec(
        collection="parents",
        id_param="parent_id",
        repo_dep=lambda: None,
        write_user_dep=lambda: None,
    )
    child = ResourceSpec(
        collection="children",
        id_param="child_id",
        repo_dep=lambda: None,
        write_user_dep=lambda: None,
        parent=parent,
    )
    router = APIRouter()
    with pytest.raises(NotImplementedError, match="parent"):
        mount_delete(
            router,
            child,
            handler=lambda **_: None,
            audit_repo_dep=lambda: None,
        )


def test_mount_delete_requires_write_user_dep():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        # write_user_dep intentionally omitted
    )
    router = APIRouter()
    with pytest.raises(ValueError, match="write_user_dep"):
        mount_delete(
            router,
            spec,
            handler=lambda **_: None,
            audit_repo_dep=lambda: None,
        )


def test_mount_delete_404_propagates_from_handler():
    """If the handler raises NotFoundError, the route surfaces it as 404
    (decorator translation). Confirms the mount doesn't swallow exceptions."""

    from src.api.common.exceptions import NotFoundError

    async def raising_handler(**kwargs):
        raise NotFoundError(detail="missing")

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = FastAPI()
    router = APIRouter(prefix=f"/{spec.collection}")
    mount_delete(
        router,
        spec,
        handler=raising_handler,
        audit_repo_dep=lambda: SimpleNamespace(name="audit_repo"),
    )
    app.include_router(router)
    client = TestClient(app)

    resp = client.delete(f"/widgets/{uuid4()}")
    assert resp.status_code == 404
