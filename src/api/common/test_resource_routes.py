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

Handlers in these tests use real repository types (`UserRepository`,
`AuditRepository`, etc.) as type annotations so the signature-synthesis
machinery in the mount layer can resolve them via the registry in
`src.repositories.dependencies`. The actual instances injected at call
time come from `app.dependency_overrides` substitutions that return
`SimpleNamespace` stubs — the test doesn't need a real DB, just to
observe the kwargs that reach the handler.
"""

from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.common.resource_routes import (
    MountError,
    QueryParam,
    ResourceSpec,
    mount_delete,
    mount_detail,
    mount_form,
    mount_list,
    mount_related_list,
    mount_state_axis,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import get_audit_repository
from src.repositories.users.user_repository import UserRepository


def _override_audit(app: FastAPI, *, stub: Any = None) -> SimpleNamespace:
    """Substitute `get_audit_repository` with a stub returning a
    `SimpleNamespace` so a test app can satisfy `audit_repo: AuditRepository`
    without a real DB session. Returns the stub the resolver returns so
    callers can identity-check it in assertions."""
    sentinel = stub if stub is not None else SimpleNamespace(name="audit_repo")
    app.dependency_overrides[get_audit_repository] = lambda: sentinel
    return sentinel


def _build_delete_app(spec: ResourceSpec, captured: dict) -> FastAPI:
    """Mount `mount_delete` for `spec` and capture every handler call into
    `captured`. Stub deps return predictable sentinels so kwargs are
    inspectable in assertions."""
    id_param = spec.id_param

    async def delete_handler(
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
        **path_kwargs: UUID,
    ):
        captured["repo"] = repo
        captured["audit_repo"] = audit_repo
        captured["requesting_user"] = requesting_user
        captured.update(path_kwargs)

    # The synthesis introspects the handler signature for known param
    # names. Path params come in via `**path_kwargs` here because the
    # tests parameterize `id_param` and we can't statically declare a
    # name that varies; so we explicitly tell the synthesis about it via
    # a wrapper handler whose signature names the actual param.
    # (Production handlers spell out e.g. `user_id: UUID` directly.)
    handler = _name_path_params(
        delete_handler, [id_param] + [s.id_param for s in _ancestors(spec)]
    )

    app = FastAPI()
    router = APIRouter(
        prefix=(
            f"/{spec.collection}"
            if spec.parent is None
            else f"/{_topmost(spec).collection}"
        )
    )
    _override_audit(app)
    mount_delete(router, spec, handler=handler)
    app.include_router(router)
    return app


def _ancestors(spec: ResourceSpec) -> list[ResourceSpec]:
    out: list[ResourceSpec] = []
    s = spec.parent
    while s is not None:
        out.append(s)
        s = s.parent
    return out


def _topmost(spec: ResourceSpec) -> ResourceSpec:
    s = spec
    while s.parent is not None:
        s = s.parent
    return s


def _name_path_params(handler, path_names: list[str]):
    """Wrap `handler` so it accepts `path_names` as explicit typed
    parameters. Used by parametric tests where the path-param name is
    derived from the spec rather than literal."""
    import inspect as _inspect

    orig_sig = _inspect.signature(handler)
    new_params = []
    for name in path_names:
        new_params.append(
            _inspect.Parameter(
                name=name,
                kind=_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=UUID,
            )
        )
    for p in orig_sig.parameters.values():
        if p.kind == _inspect.Parameter.VAR_KEYWORD:
            continue
        new_params.append(p)
    new_params.append(
        _inspect.Parameter(
            name="__path_kwargs__",
            kind=_inspect.Parameter.VAR_KEYWORD,
        )
    )

    async def wrapper(**kwargs):
        path_kwargs = {n: kwargs.pop(n) for n in path_names if n in kwargs}
        return await handler(**kwargs, **path_kwargs)

    wrapper.__signature__ = _inspect.Signature(parameters=new_params)  # type: ignore[attr-defined]
    wrapper.__name__ = handler.__name__
    wrapper.__module__ = handler.__module__
    return wrapper


def test_mount_delete_returns_204_with_hx_redirect_default():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    captured: dict = {}
    client = TestClient(_build_delete_app(spec, captured))

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
    client = TestClient(_build_delete_app(spec, captured))

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
    client = TestClient(_build_delete_app(spec, captured))

    sprocket_id = uuid4()
    resp = client.delete(f"/sprockets/{sprocket_id}")

    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == f"/sprockets-overview?last={sprocket_id}"


def test_mount_delete_subresource_path_includes_parent_id():
    """A child ResourceSpec with `parent=` mounts the path under the
    parent's id-param. Handler receives both ids by their declared kwarg
    names. The router prefix carries the topmost ancestor's collection."""
    captured: dict = {}

    parent = ResourceSpec(
        collection="parents",
        id_param="parent_id",
        repo_dep=lambda: SimpleNamespace(name="parent_repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    child = ResourceSpec(
        collection="children",
        id_param="child_id",
        repo_dep=lambda: SimpleNamespace(name="child_repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
        parent=parent,
    )

    app = FastAPI()
    router = APIRouter(prefix="/parents")
    _override_audit(app)

    async def delete_handler(
        parent_id: UUID,
        child_id: UUID,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        captured["parent_id"] = parent_id
        captured["child_id"] = child_id
        captured["repo"] = repo

    mount_delete(router, child, handler=delete_handler)
    app.include_router(router)
    client = TestClient(app)

    parent_id = uuid4()
    child_id = uuid4()
    resp = client.delete(f"/parents/{parent_id}/children/{child_id}")

    assert resp.status_code == 204
    assert captured["parent_id"] == parent_id
    assert captured["child_id"] == child_id
    assert captured["repo"].name == "child_repo"


def test_resource_spec_private_fields_without_predicate_raises():
    """Declaring `private_fields` without a predicate would silently leak
    them — the construction-time guard makes the misconfiguration loud."""
    with pytest.raises(ValueError, match="private_field_predicate"):
        ResourceSpec(
            collection="widgets",
            id_param="widget_id",
            repo_dep=lambda: None,
            private_fields=("secret",),
            # private_field_predicate intentionally omitted
        )


def test_resource_spec_private_fields_with_predicate_constructs():
    """Both set: construction succeeds and the fields round-trip."""
    predicate = lambda actor, target: False  # noqa: E731
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        private_fields=("secret",),
        private_field_predicate=predicate,
    )
    assert spec.private_fields == ("secret",)
    assert spec.private_field_predicate is predicate


def test_resource_spec_no_private_fields_no_predicate_constructs():
    """Default case (no private fields at all): predicate may stay None."""
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
    )
    assert spec.private_fields == ()
    assert spec.private_field_predicate is None


def test_mount_delete_requires_write_user_dep():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        # write_user_dep intentionally omitted
    )
    router = APIRouter()

    async def stub(
        widget_id: UUID,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        pass

    with pytest.raises(ValueError, match="write_user_dep"):
        mount_delete(router, spec, handler=stub)


def _build_read_app(spec: ResourceSpec, list_handler, detail_handler):
    """Mount mount_list + mount_detail and return a FastAPI app. Handlers
    return a context dict that the templating layer can render against
    a stub template."""
    app = FastAPI()
    router = APIRouter(prefix=f"/{spec.collection}")
    mount_list(router, spec, handler=list_handler)
    mount_detail(router, spec, handler=detail_handler)
    app.include_router(router)
    return app


def test_mount_list_renders_template_with_handler_context(monkeypatch):
    captured = {}

    async def list_handler(
        request: Request,
        repo: UserRepository,
        requesting_user: User,
    ):
        captured["repo"] = repo
        captured["requesting_user"] = requesting_user
        return {"users": ["alice", "bob"]}

    async def detail_handler(
        widget_id: UUID,
        repo: UserRepository,
        requesting_user: User,
    ):
        return {}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="widget_repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
        list_template="widgets/list.html",
        detail_template="widgets/detail.html",
    )

    rendered = {}

    def fake_html_response(*, template_name, context, request, current_user=None):
        rendered["template_name"] = template_name
        rendered["context"] = context
        rendered["current_user"] = current_user
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True})

    monkeypatch.setattr(
        "src.api.common.resource_routes.APIResponse.html_response",
        staticmethod(fake_html_response),
    )

    client = TestClient(_build_read_app(spec, list_handler, detail_handler))
    resp = client.get("/widgets")

    assert resp.status_code == 200
    assert rendered["template_name"] == "widgets/list.html"
    assert rendered["context"] == {"users": ["alice", "bob"]}
    assert captured["repo"].name == "widget_repo"


def test_mount_detail_injects_extra_typed_repo_from_registry(monkeypatch):
    """A handler asks for a typed repo (e.g. `audit_repo: AuditRepository`),
    and the synthesis resolves it via the registry in
    `src.repositories.dependencies`. No `extra_repo_deps` wiring on the
    mount call — the handler's signature IS the contract."""
    captured: dict = {}

    async def list_handler(
        request: Request,
        repo: UserRepository,
        requesting_user: User,
    ):
        return {}

    async def detail_handler(
        gadget_id: UUID,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        captured["gadget_id"] = gadget_id
        captured["repo"] = repo
        captured["audit_repo"] = audit_repo
        return {"widget": gadget_id}

    spec = ResourceSpec(
        collection="gadgets",
        id_param="gadget_id",
        repo_dep=lambda: SimpleNamespace(name="gadget_repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
        list_template="gadgets/list.html",
        detail_template="gadgets/detail.html",
    )

    monkeypatch.setattr(
        "src.api.common.resource_routes.APIResponse.html_response",
        staticmethod(
            lambda *, template_name, context, request, current_user=None: __import__(
                "fastapi"
            ).responses.JSONResponse({})
        ),
    )

    app = FastAPI()
    router = APIRouter(prefix="/gadgets")
    _override_audit(app)
    mount_list(router, spec, handler=list_handler)
    mount_detail(router, spec, handler=detail_handler)
    app.include_router(router)
    client = TestClient(app)

    gadget_id = uuid4()
    resp = client.get(f"/gadgets/{gadget_id}")

    assert resp.status_code == 200
    assert captured["audit_repo"].name == "audit_repo"  # via registry → override
    assert captured["gadget_id"] == gadget_id
    assert captured["repo"].name == "gadget_repo"


def test_mount_list_requires_list_template():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        read_user_dep=lambda: None,
        # list_template intentionally omitted
    )
    router = APIRouter()

    async def stub(request: Request, repo: UserRepository, requesting_user: User):
        return {}

    with pytest.raises(ValueError, match="list_template"):
        mount_list(router, spec, handler=stub)


def test_mount_detail_requires_detail_template():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        read_user_dep=lambda: None,
    )
    router = APIRouter()

    async def stub(widget_id: UUID, repo: UserRepository, requesting_user: User):
        return {}

    with pytest.raises(ValueError, match="detail_template"):
        mount_detail(router, spec, handler=stub)


def test_mount_raises_when_handler_asks_for_unregistered_repo_type():
    """If a handler param's type is not in the registry, the mount fails
    at registration with a clear `MountError`. Converts late 500s into
    early startup errors."""

    class _SomeUnregisteredRepo:
        pass

    async def stub(
        widget_id: UUID,
        repo: UserRepository,
        weird_repo: _SomeUnregisteredRepo,
        requesting_user: User,
    ):
        return {}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        read_user_dep=lambda: None,
        detail_template="widgets/detail.html",
    )
    router = APIRouter()
    with pytest.raises(MountError, match="_SomeUnregisteredRepo"):
        mount_detail(router, spec, handler=stub)


def _stub_html_response(monkeypatch):
    """Patch APIResponse.html_response to return a simple JSONResponse so
    tests don't need real templates. Returns the captured dict the patch
    writes into."""
    captured = {}

    def fake(*, template_name, context, request, current_user=None):
        captured["template_name"] = template_name
        captured["context"] = context
        captured["current_user"] = current_user
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True})

    monkeypatch.setattr(
        "src.api.common.resource_routes.APIResponse.html_response",
        staticmethod(fake),
    )
    return captured


def test_mount_form_create_route_at_form_path(monkeypatch):
    """on_existing=False mounts GET /<collection>/form (no id in URL)."""
    captured_handler: dict = {}

    async def form_handler(**kwargs):
        captured_handler.update(kwargs)
        return {"current_user": kwargs.get("requesting_user")}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    rendered = _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_form(router, spec, handler=form_handler, template="widgets/new.html")
    app.include_router(router)

    resp = TestClient(app).get("/widgets/form")
    assert resp.status_code == 200
    assert rendered["template_name"] == "widgets/new.html"
    assert "widget_id" not in captured_handler


def test_mount_form_edit_route_at_id_form_path(monkeypatch):
    """on_existing=True mounts GET /<collection>/{id}/form, passes id to handler."""
    captured_handler: dict = {}

    async def form_handler(
        request: Request,
        gadget_id: UUID,
        repo: UserRepository,
        requesting_user: User,
    ):
        captured_handler["gadget_id"] = gadget_id
        return {}

    spec = ResourceSpec(
        collection="gadgets",
        id_param="gadget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/gadgets")
    mount_form(
        router,
        spec,
        handler=form_handler,
        template="gadgets/edit.html",
        on_existing=True,
    )
    app.include_router(router)

    gadget_id = uuid4()
    resp = TestClient(app).get(f"/gadgets/{gadget_id}/form")
    assert resp.status_code == 200
    assert str(captured_handler["gadget_id"]) == str(gadget_id)


def test_mount_form_handler_template_name_overrides_kwarg(monkeypatch):
    """Handler returning template_name in context wins over the per-mount kwarg.
    This is what posts kind-dispatch will use in slice 7 (#252). The template_name
    key is popped so it doesn't appear in the rendered context dict."""

    async def form_handler(**kwargs):
        return {"template_name": "widgets/from-handler.html", "x": 1}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    rendered = _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_form(router, spec, handler=form_handler, template="widgets/from-kwarg.html")
    app.include_router(router)

    resp = TestClient(app).get("/widgets/form")
    assert resp.status_code == 200
    assert rendered["template_name"] == "widgets/from-handler.html"
    assert "template_name" not in rendered["context"]
    assert rendered["context"] == {"x": 1}


def test_mount_form_no_template_anywhere_raises():
    """No template on spec, no template kwarg, handler doesn't return one
    → RuntimeError at request time. The mount catches the misconfiguration
    in the request path; the route's BaseRouter wrapping in production
    surfaces this as 500. Here we use a bare APIRouter so the exception
    propagates directly through TestClient."""

    async def form_handler(**kwargs):
        return {}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_form(router, spec, handler=form_handler)
    app.include_router(router)

    with pytest.raises(RuntimeError, match="could not resolve a template"):
        TestClient(app).get("/widgets/form")


def test_mount_list_passes_query_params_to_handler(monkeypatch):
    """Each `QueryParam` reaches the handler under its declared name."""
    captured = {}

    async def list_handler(
        request: Request,
        repo: UserRepository,
        requesting_user: User,
        kind: str | None,
        active: bool,
    ):
        captured["kind"] = kind
        captured["active"] = active
        return {"items": []}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
        list_template="widgets/list.html",
    )
    _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_list(
        router,
        spec,
        handler=list_handler,
        query_params=(
            QueryParam("kind", str | None, None),
            QueryParam("active", bool, True),
        ),
    )
    app.include_router(router)

    resp = TestClient(app).get("/widgets?kind=foo&active=false")
    assert resp.status_code == 200
    assert captured["kind"] == "foo"
    assert captured["active"] is False


def test_mount_list_public_skips_auth_dep(monkeypatch):
    """`public=True` overrides the spec's read_user_dep; handler still
    receives `requesting_user=None` for kwarg uniformity. Handler must
    declare `requesting_user: User | None` to opt in to the public path."""
    captured = {}

    async def list_handler(
        request: Request,
        repo: UserRepository,
        requesting_user: User | None,
    ):
        captured["requesting_user"] = requesting_user
        return {"items": []}

    def required_user():
        raise RuntimeError("auth dep should not be called when public=True")

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=required_user,
        list_template="widgets/list.html",
    )
    _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_list(router, spec, handler=list_handler, public=True)
    app.include_router(router)

    resp = TestClient(app).get("/widgets")
    assert resp.status_code == 200
    assert captured["requesting_user"] is None


def test_mount_form_query_param_drives_handler_template_choice(monkeypatch):
    """A query param (e.g. `?kind=`) reaches the handler, and the handler's
    `template_name` in context picks the rendered template — the existing
    precedence chain handles polymorphic-by-query forms."""

    async def form_handler(
        request: Request,
        repo: UserRepository,
        requesting_user: User,
        kind: str,
    ):
        return {"template_name": f"widgets/{kind}.html"}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    rendered = _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_form(
        router,
        spec,
        handler=form_handler,
        query_params=(QueryParam("kind", str, "default"),),
    )
    app.include_router(router)

    resp = TestClient(app).get("/widgets/form?kind=variant_b")
    assert resp.status_code == 200
    assert rendered["template_name"] == "widgets/variant_b.html"


def test_mount_detail_singleton_alias_sources_id_from_session(monkeypatch):
    """`singleton_alias=("me", session_dep)` mounts an additional GET
    /<collection>/<alias> that sources the resource id from
    `session_dep().id` instead of the URL. Same handler, same template."""
    captured = {}
    session_user_id = uuid4()

    async def detail_handler(
        widget_id: UUID,
        repo: UserRepository,
        requesting_user: User,
    ):
        captured["widget_id"] = widget_id
        captured["requesting_user"] = requesting_user
        return {"x": 1}

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
        detail_template="widgets/detail.html",
    )
    _stub_html_response(monkeypatch)

    def session_dep():
        return SimpleNamespace(id=session_user_id)

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_detail(
        router,
        spec,
        handler=detail_handler,
        singleton_alias=("me", session_dep),
    )
    app.include_router(router)

    resp = TestClient(app).get("/widgets/me")
    assert resp.status_code == 200
    assert captured["widget_id"] == session_user_id
    # Parametric route still works alongside the alias:
    parametric_id = uuid4()
    resp2 = TestClient(app).get(f"/widgets/{parametric_id}")
    assert resp2.status_code == 200
    assert captured["widget_id"] == parametric_id


def test_mount_related_list_singleton_alias_sources_id_from_session(monkeypatch):
    """Same shape for related-list — the parent id is sourced from session
    when the alias path is hit."""
    captured = {}
    session_user_id = uuid4()

    async def list_handler(
        request: Request,
        parent_id: UUID,
        repo: UserRepository,
        requesting_user: User,
    ):
        captured["parent_id"] = parent_id
        captured["requesting_user"] = requesting_user
        return {"items": []}

    parent = ResourceSpec(
        collection="parents",
        id_param="parent_id",
        repo_dep=lambda: SimpleNamespace(name="parent_repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    child = ResourceSpec(
        collection="children",
        id_param="child_id",
        repo_dep=lambda: SimpleNamespace(name="child_repo"),
    )
    _stub_html_response(monkeypatch)

    def session_dep():
        return SimpleNamespace(id=session_user_id)

    app = FastAPI()
    router = APIRouter(prefix="/parents")
    mount_related_list(
        router,
        parent_spec=parent,
        child_spec=child,
        handler=list_handler,
        template="parents/children_list.html",
        singleton_alias=("me", session_dep),
    )
    app.include_router(router)

    resp = TestClient(app).get("/parents/me/children")
    assert resp.status_code == 200
    assert captured["parent_id"] == session_user_id


def test_mount_related_list_path_under_parent_id(monkeypatch):
    """`mount_related_list` mounts GET /<parent>/{parent_id}/<child>. The
    handler is invoked with the parent id under parent_spec.id_param and
    `repo` is the *child's* repo (the handler returns children)."""
    captured = {}

    async def list_handler(
        request: Request,
        parent_id: UUID,
        repo: UserRepository,
        requesting_user: User,
    ):
        captured["parent_id"] = parent_id
        captured["repo"] = repo
        return {"profiles": []}

    parent = ResourceSpec(
        collection="parents",
        id_param="parent_id",
        repo_dep=lambda: SimpleNamespace(name="parent_repo"),
        read_user_dep=lambda: SimpleNamespace(id=uuid4()),
    )
    child = ResourceSpec(
        collection="children",
        id_param="child_id",
        repo_dep=lambda: SimpleNamespace(name="child_repo"),
    )

    rendered = _stub_html_response(monkeypatch)

    app = FastAPI()
    router = APIRouter(prefix="/parents")
    mount_related_list(
        router,
        parent_spec=parent,
        child_spec=child,
        handler=list_handler,
        template="parents/children_list.html",
    )
    app.include_router(router)

    parent_id = uuid4()
    resp = TestClient(app).get(f"/parents/{parent_id}/children")

    assert resp.status_code == 200
    assert rendered["template_name"] == "parents/children_list.html"
    assert "parent_id" in captured
    assert str(captured["parent_id"]) == str(parent_id)
    # Handler's `repo` is the CHILD's repo (the handler returns children)
    assert captured["repo"].name == "child_repo"


def test_mount_related_list_requires_template():
    parent = ResourceSpec(
        collection="parents", id_param="parent_id", repo_dep=lambda: None
    )
    child = ResourceSpec(
        collection="children", id_param="child_id", repo_dep=lambda: None
    )
    router = APIRouter()
    with pytest.raises(ValueError, match="template"):
        mount_related_list(
            router,
            parent_spec=parent,
            child_spec=child,
            handler=lambda **_: {},
            template="",
        )


# --- mount_state_axis ----------------------------------------------------


class _AxisBody(BaseModel):
    state: Literal["on", "off"]


def _build_state_axis_app(spec: ResourceSpec, handler, *, axis_name="toggle", **kwargs):
    app = FastAPI()
    router = APIRouter(prefix=f"/{spec.collection}")
    _override_audit(app)
    mount_state_axis(
        router,
        spec,
        handler=handler,
        axis_name=axis_name,
        body_schema=_AxisBody,
        **kwargs,
    )
    app.include_router(router)
    return app


def test_mount_state_axis_happy_path_returns_hx_refresh_with_projected_body():
    """PUT /<collection>/{id}/<axis> calls handler, projects via
    response_to_dict, returns 200 + HX-Refresh + projected body."""
    captured: dict = {}

    async def handler(
        widget_id: UUID,
        payload: _AxisBody,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        captured["widget_id"] = widget_id
        captured["payload"] = payload
        captured["repo"] = repo
        captured["audit_repo"] = audit_repo
        return SimpleNamespace(id=widget_id, name="w1", state="on")

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = _build_state_axis_app(
        spec,
        handler,
        response_to_dict=lambda w: {"id": str(w.id), "name": w.name, "state": w.state},
    )
    widget_id = uuid4()
    resp = TestClient(app).put(f"/widgets/{widget_id}/toggle", json={"state": "on"})
    assert resp.status_code == 200
    assert resp.headers["HX-Refresh"] == "true"
    assert "HX-Redirect" not in resp.headers
    body = resp.json()
    assert body == {"id": str(widget_id), "name": "w1", "state": "on"}
    # Handler received id under the spec's id_param + the validated payload.
    assert captured["widget_id"] == widget_id
    assert isinstance(captured["payload"], _AxisBody)
    assert captured["payload"].state == "on"
    assert captured["repo"].name == "repo"
    assert captured["audit_repo"].name == "audit_repo"


def test_mount_state_axis_invalid_body_returns_422():
    async def handler(
        widget_id: UUID,
        payload: _AxisBody,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        raise AssertionError("handler should not be called for invalid body")

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = _build_state_axis_app(spec, handler)
    resp = TestClient(app).put(f"/widgets/{uuid4()}/toggle", json={"state": "bogus"})
    assert resp.status_code == 422


def test_mount_state_axis_path_includes_axis_name():
    """Wrong axis segment ⇒ 404 (route not registered under that path)."""

    async def handler(
        widget_id: UUID,
        payload: _AxisBody,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        return SimpleNamespace(id=widget_id)

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = _build_state_axis_app(spec, handler, axis_name="activation")
    # Right axis works:
    ok = TestClient(app).put(f"/widgets/{uuid4()}/activation", json={"state": "on"})
    assert ok.status_code == 200
    # Wrong axis 404s:
    bad = TestClient(app).put(f"/widgets/{uuid4()}/somethingelse", json={"state": "on"})
    assert bad.status_code == 404


def test_mount_state_axis_requires_write_user_dep():
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: None,
        # write_user_dep intentionally omitted
    )
    router = APIRouter()

    async def stub(
        widget_id: UUID,
        payload: _AxisBody,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        pass

    with pytest.raises(ValueError, match="write_user_dep"):
        mount_state_axis(
            router,
            spec,
            handler=stub,
            axis_name="toggle",
            body_schema=_AxisBody,
        )


def test_mount_state_axis_no_response_to_dict_returns_empty_body():
    """Without `response_to_dict`, the body is `{}` — handler still runs
    and the HX-Refresh header still fires."""

    async def handler(
        widget_id: UUID,
        payload: _AxisBody,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        return SimpleNamespace(id=widget_id)

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = _build_state_axis_app(spec, handler)
    resp = TestClient(app).put(f"/widgets/{uuid4()}/toggle", json={"state": "off"})
    assert resp.status_code == 200
    assert resp.json() == {}
    assert resp.headers["HX-Refresh"] == "true"


def test_mount_delete_404_propagates_from_handler():
    """If the handler raises NotFoundError, the route surfaces it as 404
    (decorator translation). Confirms the mount doesn't swallow exceptions."""

    from src.api.common.exceptions import NotFoundError

    async def raising_handler(
        widget_id: UUID,
        repo: UserRepository,
        audit_repo: AuditRepository,
        requesting_user: User,
    ):
        raise NotFoundError(detail="missing")

    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: SimpleNamespace(id=uuid4(), is_superuser=True),
    )
    app = FastAPI()
    router = APIRouter(prefix=f"/{spec.collection}")
    _override_audit(app)
    mount_delete(router, spec, handler=raising_handler)
    app.include_router(router)
    client = TestClient(app)

    resp = client.delete(f"/widgets/{uuid4()}")
    assert resp.status_code == 404
