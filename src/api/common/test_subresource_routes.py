"""Tests for `src/api/common/subresource_routes.py`.

Registers a tiny `widgets` sub-resource against a stub router and exercises
the three POST/PATCH/DELETE routes end-to-end. Validates that the helper
forwards the child-id to the spec's logic handlers under the right kwarg
name and emits the same response shape as the hand-written equivalents.
"""

from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, TypeAdapter

from .subresource_routes import (
    SubresourceDeps,
    SubresourceSpec,
    register_subresource_routes,
)


class _WidgetCreate(BaseModel):
    name: str

    model_config = ConfigDict(extra="forbid")


class _WidgetUpdate(BaseModel):
    name: str

    model_config = ConfigDict(extra="forbid")


def _build_app(spec: SubresourceSpec, captured: dict) -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/providers")
    register_subresource_routes(
        router,
        spec,
        deps=SubresourceDeps(
            repo=lambda: SimpleNamespace(name="repo"),
            audit_repo=lambda: SimpleNamespace(name="audit_repo"),
            user=lambda: SimpleNamespace(id=uuid4(), is_superuser=False),
        ),
    )
    app.include_router(router)
    return app


def test_create_route_calls_handler_with_kwargs():
    captured = {}

    async def create_handler(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4())

    async def update_handler(**kwargs):
        return None

    async def delete_handler(**kwargs):
        return None

    spec = SubresourceSpec(
        collection="widgets",
        child_id_param="widget_id",
        create_adapter=TypeAdapter(_WidgetCreate),
        update_adapter=TypeAdapter(_WidgetUpdate),
        read_to_dict=lambda r: {"id": str(r.id)},
        create_handler=create_handler,
        update_handler=update_handler,
        delete_handler=delete_handler,
    )

    parent_id = uuid4()
    client = TestClient(_build_app(spec, captured))
    resp = client.post(f"/providers/{parent_id}/widgets", data={"name": "x"})

    assert resp.status_code == 201
    assert resp.headers["Location"] == f"/providers/{parent_id}"
    assert resp.headers["HX-Redirect"] == f"/providers/{parent_id}/form"
    assert captured["provider_id"] == parent_id
    assert captured["payload"].name == "x"


def test_patch_route_forwards_child_id_under_spec_kwarg():
    captured = {}

    async def update_handler(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4())

    async def create_handler(**kwargs):
        return SimpleNamespace(id=uuid4())

    async def delete_handler(**kwargs):
        return None

    spec = SubresourceSpec(
        collection="widgets",
        child_id_param="widget_id",
        create_adapter=TypeAdapter(_WidgetCreate),
        update_adapter=TypeAdapter(_WidgetUpdate),
        read_to_dict=lambda r: {"id": str(r.id)},
        create_handler=create_handler,
        update_handler=update_handler,
        delete_handler=delete_handler,
    )

    parent_id, child_id = uuid4(), uuid4()
    client = TestClient(_build_app(spec, captured))
    resp = client.patch(
        f"/providers/{parent_id}/widgets/{child_id}", data={"name": "y"}
    )

    assert resp.status_code == 200
    assert resp.headers["HX-Redirect"] == f"/providers/{parent_id}/form"
    # The helper must forward child_id under the spec's kwarg name
    # (preserves existing handler signatures like
    # `handle_update_licensure(licensure_id=...)`).
    assert captured["widget_id"] == child_id
    assert "child_id" not in captured


def test_delete_route_returns_204_with_hx_redirect():
    captured = {}

    async def delete_handler(**kwargs):
        captured.update(kwargs)

    async def create_handler(**kwargs):
        return SimpleNamespace(id=uuid4())

    async def update_handler(**kwargs):
        return SimpleNamespace(id=uuid4())

    spec = SubresourceSpec(
        collection="widgets",
        child_id_param="widget_id",
        create_adapter=TypeAdapter(_WidgetCreate),
        update_adapter=TypeAdapter(_WidgetUpdate),
        read_to_dict=lambda r: {"id": str(r.id)},
        create_handler=create_handler,
        update_handler=update_handler,
        delete_handler=delete_handler,
    )

    parent_id, child_id = uuid4(), uuid4()
    client = TestClient(_build_app(spec, captured))
    resp = client.delete(f"/providers/{parent_id}/widgets/{child_id}")

    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == f"/providers/{parent_id}/form"
    assert captured["widget_id"] == child_id


def test_create_payload_validation_returns_422():
    async def create_handler(**kwargs):
        return SimpleNamespace(id=uuid4())

    async def update_handler(**kwargs):
        return None

    async def delete_handler(**kwargs):
        return None

    spec = SubresourceSpec(
        collection="widgets",
        child_id_param="widget_id",
        create_adapter=TypeAdapter(_WidgetCreate),
        update_adapter=TypeAdapter(_WidgetUpdate),
        read_to_dict=lambda r: {"id": str(r.id)},
        create_handler=create_handler,
        update_handler=update_handler,
        delete_handler=delete_handler,
    )

    parent_id = uuid4()
    client = TestClient(_build_app(spec, {}))
    # Missing required `name` field — schema rejects with 422.
    resp = client.post(f"/providers/{parent_id}/widgets", data={})
    assert resp.status_code == 422
