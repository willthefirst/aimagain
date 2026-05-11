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


# --- mount_entity dispatcher tests ---------------------------------------


from src.api.common.entity_spec import EntitySpec as _EntitySpec  # noqa: E402
from src.api.common.entity_spec import (  # noqa: E402
    RelatedListSubresource as _RelatedSub,
)
from src.api.common.entity_spec import RouteSet as _RouteSet  # noqa: E402
from src.api.common.entity_spec import StateAxis as _StateAxis  # noqa: E402
from src.api.common.entity_spec import Templates as _Templates  # noqa: E402
from src.api.common.resource_routes import mount_entity  # noqa: E402
from src.logic.audit import AuditAction as _AuditAction  # noqa: E402
from src.logic.audit import AuditedResource as _AuditedResource  # noqa: E402


def _stub_axis_handler():
    """Module-level callable that `test_mount_entity_state_axis_resolves_handler_path`
    targets via `handler_path` to exercise the importlib resolver."""
    return None


async def _stub_detail_extras(**_kw):
    """Module-level extras callable targeted via `detail_extras_path` in
    `test_mount_entity_detail_extras_threaded_to_factory`. Real attribute
    (not a lambda) so `importlib.import_module` + `getattr` can find it."""
    return {}


async def _stub_list_extras(**_kw):
    return {}


def _stub_audit() -> _AuditedResource:
    return _AuditedResource(
        type="thing",
        snapshot=lambda obj: {"id": "x"},
        create=_AuditAction.CREATE_USER,
        update=_AuditAction.UPDATE_USER,
        delete=_AuditAction.DELETE_USER,
    )


def test_mount_entity_skips_routes_not_opted_in():
    """`mount_entity` only mounts the verbs `entity.routes` opts into.
    With everything False, no helpers are called."""
    calls = []
    import src.api.common.resource_routes as rr

    monkeys = []
    for fn_name in (
        "mount_list",
        "mount_detail",
        "mount_create",
        "mount_update",
        "mount_delete",
        "mount_form",
        "mount_state_axis",
        "mount_related_list",
    ):
        orig = getattr(rr, fn_name)

        def _capture(*args, _name=fn_name, **kw):
            calls.append(_name)

        monkeys.append((fn_name, orig))
        setattr(rr, fn_name, _capture)
    try:
        spec = _EntitySpec(
            name="thing",
            url_collection="things",
            id_param="thing_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
        )
        mount_entity(None, spec, handlers={})
    finally:
        for n, orig in monkeys:
            setattr(rr, n, orig)
    assert calls == []  # nothing opted in → nothing dispatched


def test_mount_entity_dispatches_each_opted_in_verb():
    """`RouteSet` flags drive dispatch to the matching mount helpers."""
    calls = []
    import src.api.common.resource_routes as rr

    monkeys = []
    for fn_name in (
        "mount_list",
        "mount_detail",
        "mount_create",
        "mount_update",
        "mount_delete",
        "mount_form",
    ):
        orig = getattr(rr, fn_name)
        setattr(
            rr,
            fn_name,
            lambda *a, _n=fn_name, **k: calls.append((_n, k)),
        )
        monkeys.append((fn_name, orig))
    try:
        from pydantic import TypeAdapter

        spec = _EntitySpec(
            name="thing",
            url_collection="things",
            id_param="thing_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            routes=_RouteSet(
                list=True,
                detail=True,
                create=True,
                update=True,
                delete=True,
                form_new=True,
                form_edit=True,
            ),
            create_adapter=TypeAdapter(_AxisBody),
            update_adapter=TypeAdapter(_AxisBody),
            templates=_Templates(
                list="t/list.html",
                detail="t/detail.html",
                form_new="t/new.html",
                form_edit="t/edit.html",
            ),
        )
        mount_entity(
            None,
            spec,
            handlers={
                "list": lambda: None,
                "detail": lambda: None,
                "create": lambda: None,
                "update": lambda: None,
                "delete": lambda: None,
                "form_new": lambda: None,
                "form_edit": lambda: None,
            },
        )
    finally:
        for n, orig in monkeys:
            setattr(rr, n, orig)

    names = [c[0] for c in calls]
    assert "mount_list" in names
    assert "mount_detail" in names
    assert "mount_create" in names
    assert "mount_update" in names
    assert "mount_delete" in names
    # form_new + form_edit both → mount_form (twice)
    assert names.count("mount_form") == 2


def test_mount_entity_dispatches_state_axes():
    calls = []
    import src.api.common.resource_routes as rr

    orig = rr.mount_state_axis
    rr.mount_state_axis = lambda *a, **k: calls.append(k)
    try:
        spec = _EntitySpec(
            name="thing",
            url_collection="things",
            id_param="thing_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            state_axes=(
                _StateAxis(
                    name="activation",
                    body_schema=_AxisBody,
                    action=_AuditAction.SET_USER_ACTIVATION,
                ),
            ),
        )
        mount_entity(None, spec, handlers={"activation": lambda: None})
    finally:
        rr.mount_state_axis = orig
    assert len(calls) == 1
    assert calls[0]["axis_name"] == "activation"


def test_mount_entity_dispatches_related_list_subresources():
    calls = []
    import src.api.common.resource_routes as rr

    orig = rr.mount_related_list
    rr.mount_related_list = lambda *a, **k: calls.append(k)
    try:
        child_spec = ResourceSpec(
            collection="children",
            id_param="child_id",
            repo_dep=lambda: None,
        )
        spec = _EntitySpec(
            name="parent",
            url_collection="parents",
            id_param="parent_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            subresources=(_RelatedSub(child_spec=child_spec, template="x/list.html"),),
        )
        mount_entity(None, spec, handlers={"children": lambda: None})
    finally:
        rr.mount_related_list = orig
    assert len(calls) == 1
    assert calls[0]["template"] == "x/list.html"


def test_mount_entity_state_axis_resolves_handler_path():
    """When a state axis declares `handler_path` and `handlers` omits the
    key, `mount_entity` resolves the dotted path via importlib."""
    calls = []
    import src.api.common.resource_routes as rr

    orig = rr.mount_state_axis
    rr.mount_state_axis = lambda *a, **k: calls.append(k)
    try:
        spec = _EntitySpec(
            name="thing",
            url_collection="things",
            id_param="thing_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            state_axes=(
                _StateAxis(
                    name="activation",
                    body_schema=_AxisBody,
                    action=_AuditAction.SET_USER_ACTIVATION,
                    handler_path=(
                        "src.api.common.test_resource_routes._stub_axis_handler"
                    ),
                ),
            ),
        )
        mount_entity(None, spec, handlers={})
    finally:
        rr.mount_state_axis = orig
    assert len(calls) == 1
    assert calls[0]["handler"] is _stub_axis_handler


def test_mount_entity_state_axis_explicit_handler_wins_over_path():
    """An explicit handler in `handlers={}` overrides the spec's path."""
    calls = []
    import src.api.common.resource_routes as rr

    orig = rr.mount_state_axis
    rr.mount_state_axis = lambda *a, **k: calls.append(k)

    def explicit():
        return None

    try:
        spec = _EntitySpec(
            name="thing",
            url_collection="things",
            id_param="thing_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            state_axes=(
                _StateAxis(
                    name="activation",
                    body_schema=_AxisBody,
                    action=_AuditAction.SET_USER_ACTIVATION,
                    handler_path=(
                        "src.api.common.test_resource_routes._stub_axis_handler"
                    ),
                ),
            ),
        )
        mount_entity(None, spec, handlers={"activation": explicit})
    finally:
        rr.mount_state_axis = orig
    assert calls[0]["handler"] is explicit


def test_mount_entity_handler_path_missing_attr_raises_clear_error():
    spec = _EntitySpec(
        name="thing",
        url_collection="things",
        id_param="thing_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        state_axes=(
            _StateAxis(
                name="activation",
                body_schema=_AxisBody,
                action=_AuditAction.SET_USER_ACTIVATION,
                handler_path=("src.api.common.test_resource_routes._missing_handler"),
            ),
        ),
    )
    with pytest.raises(AttributeError, match="_missing_handler"):
        mount_entity(None, spec, handlers={})


def test_mount_entity_extra_handler_keys_raises_value_error():
    """Typos in handler keys are caught at mount time, not silently no-op."""
    spec = _EntitySpec(
        name="thing",
        url_collection="things",
        id_param="thing_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(list=True),
    )
    import src.api.common.resource_routes as rr

    orig = rr.mount_list
    rr.mount_list = lambda *a, **k: None
    try:
        with pytest.raises(ValueError, match="not consumed"):
            mount_entity(
                None,
                spec,
                handlers={"list": lambda: None, "lsit": lambda: None},
            )
    finally:
        rr.mount_list = orig


def test_mount_entity_owned_subentity_parent_mismatch_raises():
    """Catches a passed-in owned subentity whose `parent` is wrong entity."""
    other_parent = _EntitySpec(
        name="other",
        url_collection="others",
        id_param="other_id",
        model=SimpleNamespace,
    )
    child = _EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=SimpleNamespace,
        parent=other_parent,
        routes=_RouteSet(delete=True),
        audit=_stub_audit(),
    )
    correct_parent = _EntitySpec(
        name="thing",
        url_collection="things",
        id_param="thing_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
    )
    with pytest.raises(ValueError, match="parent"):
        mount_entity(None, correct_parent, handlers={}, owned_subentities=(child,))


def test_mount_entity_owned_subentity_auto_binds_default_factory():
    """Standard CRUD verbs on an owned subentity bind to
    `make_<verb>_handler(child)` when no explicit
    `<owned.name>.<verb>` key is supplied."""
    from pydantic import TypeAdapter

    parent = _EntitySpec(
        name="parent",
        url_collection="parents",
        id_param="parent_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
    )
    child = _EntitySpec(
        name="child",
        url_collection="children",
        id_param="child_id",
        model=SimpleNamespace,
        parent=parent,
        audit=_stub_audit(),
        create_adapter=TypeAdapter(_AxisBody),
        update_adapter=TypeAdapter(_AxisBody),
        routes=_RouteSet(create=True, update=True, delete=True),
    )

    captured: list[Callable[..., Any]] = []
    import src.api.common.resource_routes as rr

    originals = {}
    for fn_name in ("mount_create", "mount_update", "mount_delete"):
        originals[fn_name] = getattr(rr, fn_name)
        setattr(
            rr,
            fn_name,
            lambda *a, _n=fn_name, **k: captured.append((_n, k.get("handler"))),
        )
    try:
        mount_entity(None, parent, handlers={}, owned_subentities=(child,))
    finally:
        for n, orig in originals.items():
            setattr(rr, n, orig)

    handler_names = {n: h.__name__ for n, h in captured}
    assert handler_names == {
        "mount_create": "_handle_create_child",
        "mount_update": "_handle_update_child",
        "mount_delete": "_handle_delete_child",
    }


def test_mount_entity_owned_subentity_explicit_handler_overrides_default():
    """An explicit `<owned.name>.<verb>` key wins over the
    auto-bound factory default."""
    from pydantic import TypeAdapter

    parent = _EntitySpec(
        name="parent",
        url_collection="parents",
        id_param="parent_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
    )
    child = _EntitySpec(
        name="child",
        url_collection="children",
        id_param="child_id",
        model=SimpleNamespace,
        parent=parent,
        audit=_stub_audit(),
        create_adapter=TypeAdapter(_AxisBody),
        update_adapter=TypeAdapter(_AxisBody),
        routes=_RouteSet(create=True, update=True, delete=True),
    )

    async def bespoke_create(**_kw):  # pragma: no cover
        return None

    captured: list[Callable[..., Any]] = []
    import src.api.common.resource_routes as rr

    originals = {}
    for fn_name in ("mount_create", "mount_update", "mount_delete"):
        originals[fn_name] = getattr(rr, fn_name)
        setattr(
            rr,
            fn_name,
            lambda *a, _n=fn_name, **k: captured.append((_n, k.get("handler"))),
        )
    try:
        mount_entity(
            None,
            parent,
            handlers={"child.create": bespoke_create},
            owned_subentities=(child,),
        )
    finally:
        for n, orig in originals.items():
            setattr(rr, n, orig)

    by_mount = dict(captured)
    assert by_mount["mount_create"] is bespoke_create
    # update + delete fall back to factory defaults.
    assert by_mount["mount_update"].__name__ == "_handle_update_child"
    assert by_mount["mount_delete"].__name__ == "_handle_delete_child"


# --- top-level factory auto-bind ----------------------------------------


def _capture_top_level_mounts():
    """Stub the per-verb mount helpers + return captured (name, kwargs) list."""
    import src.api.common.resource_routes as rr

    captured: list[tuple[str, dict]] = []
    originals: dict[str, Any] = {}
    for fn_name in (
        "mount_list",
        "mount_detail",
        "mount_create",
        "mount_update",
        "mount_delete",
        "mount_form",
    ):
        originals[fn_name] = getattr(rr, fn_name)
        setattr(
            rr,
            fn_name,
            lambda *a, _n=fn_name, **k: captured.append((_n, k)),
        )

    def restore():
        for n, orig in originals.items():
            setattr(rr, n, orig)

    return captured, restore


def test_mount_entity_top_level_auto_binds_factory_handlers():
    """An opted-in standard-CRUD verb (`update`, `delete`, `form_edit`)
    with no entry in handlers gets a `make_<verb>_handler(entity)` build,
    stitched onto `module` as `<module>._handle_<verb>_<entity>`."""
    from pydantic import TypeAdapter

    spec = _EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(update=True, delete=True, form_edit=True),
        create_adapter=TypeAdapter(_AxisBody),
        update_adapter=TypeAdapter(_AxisBody),
        templates=_Templates(form_edit="w/edit.html"),
    )

    captured, restore = _capture_top_level_mounts()
    try:
        mount_entity(None, spec, handlers={})
    finally:
        restore()

    by_mount = {n: k for n, k in captured}
    assert by_mount["mount_update"]["handler"].__name__ == "_handle_update_widget"
    assert by_mount["mount_delete"]["handler"].__name__ == "_handle_delete_widget"
    assert by_mount["mount_form"]["handler"].__name__ == "_handle_get_widget_edit_form"

    # The built handlers are stitched onto this test module (auto-detected
    # from the caller frame) so `_resolve_handler` (and contract-test
    # monkey-patches) find them via
    # `getattr(sys.modules[fn.__module__], fn.__name__)`.
    import sys

    mod = sys.modules[__name__]
    assert getattr(mod, "_handle_update_widget").__module__ == __name__
    assert getattr(mod, "_handle_delete_widget").__module__ == __name__


def test_mount_entity_explicit_handler_overrides_top_level_auto_bind():
    """An explicit `handlers[verb]` for a standard-CRUD verb wins over
    the factory default — bespoke handlers (self-guard delete, inline-
    credentials create) keep working."""
    from pydantic import TypeAdapter

    spec = _EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(update=True, delete=True),
        update_adapter=TypeAdapter(_AxisBody),
    )

    async def bespoke_delete(**_kw):  # pragma: no cover
        return None

    captured, restore = _capture_top_level_mounts()
    try:
        mount_entity(
            None,
            spec,
            handlers={"delete": bespoke_delete},
        )
    finally:
        restore()

    by_mount = {n: k for n, k in captured}
    assert by_mount["mount_delete"]["handler"] is bespoke_delete
    assert by_mount["mount_update"]["handler"].__name__ == "_handle_update_widget"


def test_mount_entity_top_level_auto_bind_detects_caller_module():
    """Auto-bind walks the call stack to find the caller's `__name__`
    and stitches the built handler into that module's namespace, so
    contract-test patches at `<routes module>._handle_<verb>` resolve
    to the patched version without route files passing `module=`."""
    spec = _EntitySpec(
        name="gadget",
        url_collection="gadgets",
        id_param="gadget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(delete=True),
    )
    captured, restore = _capture_top_level_mounts()
    try:
        mount_entity(None, spec, handlers={})
    finally:
        restore()

    import sys

    mod = sys.modules[__name__]
    built = getattr(mod, "_handle_delete_gadget")
    assert built.__module__ == __name__
    by_mount = {n: k for n, k in captured}
    assert by_mount["mount_delete"]["handler"] is built


def test_mount_entity_detail_extras_threaded_to_factory():
    """`detail_extras_path` on the spec resolves via `importlib` at
    mount time and threads into `make_detail_handler`; the synthesis
    adds the typed-repo kwargs (from `detail_extras_repos`) to the
    built handler's signature."""
    spec = _EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(detail=True),
        templates=_Templates(detail="w/detail.html"),
        detail_extras_path=f"{__name__}._stub_detail_extras",
        detail_extras_repos=(("user_favorite_repo", UserRepository),),
    )

    captured, restore = _capture_top_level_mounts()
    try:
        mount_entity(None, spec, handlers={})
    finally:
        restore()

    detail_handler = next(k["handler"] for n, k in captured if n == "mount_detail")
    import inspect

    params = inspect.signature(detail_handler).parameters
    assert "user_favorite_repo" in params


def test_mount_entity_detail_extras_with_explicit_handler_raises():
    """`detail_extras_path` is for the factory-built path; declaring it
    on the spec alongside an explicit `handlers["detail"]` is ambiguous
    (the explicit handler would silently win) — surface at mount time."""
    spec = _EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(detail=True),
        templates=_Templates(detail="w/detail.html"),
        detail_extras_path=f"{__name__}._stub_detail_extras",
    )

    async def my_detail(**_kw):  # pragma: no cover
        return {}

    with pytest.raises(ValueError, match="detail_extras_path"):
        mount_entity(
            None,
            spec,
            handlers={"detail": my_detail},
        )


def test_spec_detail_extras_without_detail_route_raises():
    """Declaring extras_path on a spec whose routes.detail is False is
    dead config — the extras would never run. Surfaces at spec
    construction time (loud and immediate)."""
    with pytest.raises(ValueError, match="routes.detail is False"):
        _EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            routes=_RouteSet(),  # detail off
            detail_extras_path=f"{__name__}._stub_detail_extras",
        )


def test_spec_detail_extras_repos_without_path_raises():
    """`detail_extras_repos` without `detail_extras_path` is dead config
    — the typed-repo kwargs would have no consumer. Surfaces at spec
    construction time."""
    with pytest.raises(ValueError, match="detail_extras_repos"):
        _EntitySpec(
            name="widget",
            url_collection="widgets",
            id_param="widget_id",
            model=SimpleNamespace,
            audit=_stub_audit(),
            routes=_RouteSet(detail=True),
            templates=_Templates(detail="w/detail.html"),
            detail_extras_repos=(("x", UserRepository),),
        )


def test_spec_list_extras_path_threaded_to_factory():
    """`list_extras_path` resolves via importlib and threads into
    `make_list_handler`."""
    from pydantic import TypeAdapter

    spec = _EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_stub_audit(),
        routes=_RouteSet(list=True),
        templates=_Templates(list="w/list.html"),
        list_extras_path=f"{__name__}._stub_list_extras",
        # `repo.list_widgets` would be called; no need to wire a stub,
        # we just want to verify the auto-bind succeeds.
    )
    del TypeAdapter  # silence unused import linters
    captured, restore = _capture_top_level_mounts()
    try:
        mount_entity(None, spec, handlers={})
    finally:
        restore()
    list_handler = next(k["handler"] for n, k in captured if n == "mount_list")
    assert list_handler.__name__ == "_handle_list_widget"


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
