"""Tests for `handle_create`, `make_create_handler`, and `mount_create`.

`handle_create` / `make_create_handler` tests cover the core create path
(persist, audit, subentity, polymorphic, payload_authz). `mount_create`
tests focus on the form-error-rerender branching.

`mount_create`'s default path (parse → validate → call handler → 201) is
covered by every entity's route-level tests; the tests here pin the
*pattern* that's new with `form_error_render`:

  - **`build_form_errors_dict`** is the pure helper that collapses a
    422 detail list into the per-field dict the form macros consume.
    Tests cover the kind-prefix-stripping rule, repeated-field
    collision policy, and malformed-input degradation. Pure function
    → table-driven test.
  - **The dispatch branching** (HX-Request vs not, form_error_render
    on vs off) goes through a synthetic FastAPI app: the renderer is
    monkeypatched so the test runs without real templating, and the
    test asserts what `mount_create` *did* (raised 422 vs. invoked the
    renderer) rather than what the renderer produced.

Per-entity HTML-shape assertions (e.g. "the age_groups select carries
`aria-invalid='true'`") belong at the macro layer
(`src/framework/templates/_shared/test_form_fields.py`); per-entity
integration smokes ("POST returns 200 + HTML that mentions the failing
field") belong at the route layer. This file owns the *framework
contract*: any entity opting into `form_error_render` gets these
semantics regardless of what its form template looks like.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass as _dc
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter

from src.framework.audit.core import AuditAction, AuditedResource
from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts.conftest import (
    FakeAuditRepo,
    FakeRepo,
    ParentRow,
    make_audit,
    make_user,
    parent_spec,
)
from src.framework.dispatch.mounts.create import (
    build_form_errors_dict,
    handle_create,
    make_create_handler,
    mount_create,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.persistence.polymorphic import DiscriminatorRegistry

# --- build_form_errors_dict (pure helper) --------------------------------


class TestBuildFormErrorsDict:
    """Pure unit tests for the 422-detail → `{field: msg}` collapse.

    Table-driven because the function's only contract is the
    loc-shape-to-dict mapping rule; integration of this function with
    the rest of the rerender path is covered by the dispatch tests
    below."""

    def test_top_level_loc_maps_to_field_key(self) -> None:
        errors = [
            {"loc": ("age_groups",), "msg": "field required", "type": "missing"},
        ]
        assert build_form_errors_dict(errors) == {"age_groups": "field required"}

    def test_discriminated_union_prefix_stripped_when_kind_matches(self) -> None:
        """Pydantic prefixes `loc` with the kind discriminator on a
        tagged union; the form template looks up by bare field name,
        so the prefix has to be stripped when `kind` is supplied."""
        errors = [
            {
                "loc": ("clinician_opening", "age_groups"),
                "msg": "field required",
                "type": "missing",
            },
        ]
        out = build_form_errors_dict(errors, kind="clinician_opening")
        assert out == {"age_groups": "field required"}

    def test_prefix_not_stripped_when_kind_mismatch(self) -> None:
        """Kind mismatch (the first loc segment isn't the supplied
        kind) leaves the loc alone — we read the first segment as the
        field name. Defends against silently swallowing errors when a
        future discriminator naming changes."""
        errors = [
            {
                "loc": ("other_kind", "age_groups"),
                "msg": "bad",
                "type": "x",
            },
        ]
        out = build_form_errors_dict(errors, kind="clinician_opening")
        assert out == {"other_kind": "bad"}

    def test_first_message_wins_per_field(self) -> None:
        """Repeated errors on the same field — pick the first so the
        user sees a stable message instead of one that re-orders across
        Pydantic versions."""
        errors = [
            {"loc": ("x",), "msg": "first", "type": "a"},
            {"loc": ("x",), "msg": "second", "type": "b"},
        ]
        assert build_form_errors_dict(errors) == {"x": "first"}

    def test_malformed_entries_skipped_silently(self) -> None:
        """Missing `loc` / missing `msg` / non-dict entry / non-list
        input all degrade to "no entry" rather than raising. The
        rerender path is on the failure side of a request — raising
        here would 500 instead of just dropping the inline message."""
        errors = [
            {"msg": "no loc"},
            {"loc": ("ok",)},
            "not a dict",
            {"loc": (), "msg": "empty loc"},
        ]
        assert build_form_errors_dict(errors) == {}
        assert build_form_errors_dict(None) == {}  # type: ignore[arg-type]
        assert build_form_errors_dict("not a list") == {}  # type: ignore[arg-type]

    def test_prefix_only_loc_is_skipped(self) -> None:
        """A loc that's just `(kind,)` with nothing after collapses to
        empty and is skipped — no field name to attach to."""
        errors = [
            {"loc": ("clinician_opening",), "msg": "x", "type": "y"},
        ]
        assert build_form_errors_dict(errors, kind="clinician_opening") == {}


# --- mount_create dispatch branching -------------------------------------


class _Body(BaseModel):
    """Minimal schema: `x` is required, so an empty POST body always
    produces a single-field 422 the dispatch tests can rely on."""

    x: str


def _build_app(
    *,
    form_error_render: bool,
    entity_spec: Any = None,
    handler_raises: Any = None,
) -> FastAPI:
    """Synthetic FastAPI app with one `POST /widgets` route mounted via
    `mount_create`. Stub deps return predictable sentinels so handler
    invocation can be observed without a real DB / audit layer.

    `handler_raises`, if set, is raised from the stub handler so tests
    can exercise the handler-error rerender branch (e.g. a 400 from a
    post-create gate).
    """
    sentinel_user = SimpleNamespace(id=uuid4(), is_superuser=True)
    spec = ResourceSpec(
        collection="widgets",
        id_param="widget_id",
        repo_dep=lambda: SimpleNamespace(name="repo"),
        write_user_dep=lambda: sentinel_user,
        create_adapter=TypeAdapter(_Body),
        form_error_render=form_error_render,
        entity_spec=entity_spec,
    )

    async def handler(payload, repo, requesting_user, request):  # noqa: ARG001
        if handler_raises is not None:
            raise handler_raises
        # Sentinel "created" object; the success path serializes its id.
        return SimpleNamespace(id=uuid4())

    app = FastAPI()
    router = APIRouter(prefix="/widgets")
    mount_create(router, spec, handler=handler)
    app.include_router(router)
    return app


def _stub_renderer_returning(html: str) -> Any:
    """Build a stub for `APIResponse.html_response` that returns a real
    `Response` carrying `html`, and records the call so the test can
    assert on the context that landed."""
    calls: list[dict] = []

    def stub(template_name, context, request, *, current_user=None, status_code=200):
        calls.append(
            {
                "template_name": template_name,
                "context": context,
                "current_user": current_user,
                "status_code": status_code,
            }
        )
        return Response(content=html, media_type="text/html", status_code=status_code)

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


def _fake_entity_spec(
    *, discriminator: Any = None, form_new_template: str | None = "widgets/new.html"
) -> SimpleNamespace:
    """Minimal stand-in for the `EntitySpec` back-ref. Only the
    attributes `_render_form_with_errors` reads need to be present —
    `discriminator` for the kind branch, `templates.form_new` for the
    fallback template. `handle_get_new_form` is patched out in the
    tests that exercise the renderer, so its richer demands aren't
    needed here."""
    return SimpleNamespace(
        discriminator=discriminator,
        templates=SimpleNamespace(form_new=form_new_template),
    )


def test_mount_create_with_hx_request_and_form_error_render_invokes_renderer() -> None:
    """The headline path: HX-Request + opted-in spec + validation
    failure → renderer is called and the response carries a 422
    status code (RFC 9110 §15.5.21 "Unprocessable Content"). The
    htmx `response-targets` extension swaps the body on the matching
    `hx-target-4xx` declaration in the form fragment.

    Pre-`response-targets` adoption this asserted 200 (the trade-off
    htmx forced when its default response handler only swapped on
    2xx). Now that the extension is wired in `base.html`, the
    rerender returns a semantically-correct 422 and the swap still
    fires."""
    app = _build_app(form_error_render=True, entity_spec=_fake_entity_spec())
    renderer = _stub_renderer_returning("<form>rendered</form>")
    with (
        patch(
            "src.framework.http.form_rerender.APIResponse.html_response",
            new=renderer,
        ),
        patch(
            "src.framework.dispatch.mounts.form.handle_get_new_form",
            new=_fake_handle_get_new_form,
        ),
    ):
        client = TestClient(app)
        # POST with no `x` → 422 from validation; HX-Request opts into
        # the rerender branch.
        resp = client.post("/widgets", data={}, headers={"HX-Request": "true"})

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == "<form>rendered</form>"
    assert len(renderer.calls) == 1
    ctx = renderer.calls[0]["context"]
    # The renderer received the framework-built `form_errors` /
    # `form_values` keys — the per-form template's only job is to read
    # them.
    assert ctx["form_errors"] == {"x": "Field required"}
    assert ctx["form_values"] == {}


def test_mount_create_without_hx_request_falls_through_to_json_422() -> None:
    """No `HX-Request` header → JSON 422, even when the spec opted in.
    Preserves the API contract for non-HTMX callers."""
    app = _build_app(form_error_render=True, entity_spec=_fake_entity_spec())
    renderer = _stub_renderer_returning("<form>should not be called</form>")
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response",
        new=renderer,
    ):
        client = TestClient(app)
        resp = client.post("/widgets", data={})

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    assert renderer.calls == []


def test_mount_create_with_hx_request_but_no_opt_in_falls_through_to_json_422() -> None:
    """Spec without `form_error_render` → JSON 422 even on HX-Request.
    Default behavior is unchanged; the opt-in is the *only* trigger."""
    app = _build_app(form_error_render=False)
    renderer = _stub_renderer_returning("<form>should not be called</form>")
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response",
        new=renderer,
    ):
        client = TestClient(app)
        resp = client.post("/widgets", data={}, headers={"HX-Request": "true"})

    assert resp.status_code == 422
    assert renderer.calls == []


def test_mount_create_opted_in_but_missing_entity_spec_falls_back_to_422() -> None:
    """Defensive: a ResourceSpec built outside `EntitySpec.to_resource_spec()`
    can carry `form_error_render=True` without an `entity_spec` back-ref.
    Rather than 500 on a None-deref, the rerender path bails to the
    original 422 so the caller sees the validation failure."""
    app = _build_app(form_error_render=True, entity_spec=None)
    client = TestClient(app)
    resp = client.post("/widgets", data={}, headers={"HX-Request": "true"})

    assert resp.status_code == 422


def test_mount_create_handler_400_with_hx_request_rerenders_with_banner() -> None:
    """When the create handler raises a 400 (e.g. the NPPES verification
    gate in the clinician/org `after_create` hooks), an HX-Request
    client on an opted-in spec gets the form re-rendered with the
    handler's `detail` as a single form-level banner, status 400, so
    the htmx `response-targets` extension swaps it in place."""
    from src.framework.http.exceptions import BadRequestError

    app = _build_app(
        form_error_render=True,
        entity_spec=_fake_entity_spec(),
        handler_raises=BadRequestError(detail="NPI verification failed"),
    )
    renderer = _stub_renderer_returning("<form>rendered</form>")
    with (
        patch(
            "src.framework.http.form_rerender.APIResponse.html_response",
            new=renderer,
        ),
        patch(
            "src.framework.dispatch.mounts.form.handle_get_new_form",
            new=_fake_handle_get_new_form,
        ),
    ):
        client = TestClient(app)
        resp = client.post("/widgets", data={"x": "ok"}, headers={"HX-Request": "true"})

    assert resp.status_code == 400
    assert resp.text == "<form>rendered</form>"
    ctx = renderer.calls[0]["context"]
    assert ctx["form_banner_text"] == "NPI verification failed"
    # The raw submitted values land in `form_values` so the user
    # doesn't lose what they typed.
    assert ctx["form_values"] == {"x": "ok"}


def test_mount_create_handler_400_without_hx_falls_through_to_json_400() -> None:
    """Non-HTMX callers still get the raw 400 JSON — the rerender
    branch is gated on `HX-Request: true`."""
    from src.framework.http.exceptions import BadRequestError

    app = _build_app(
        form_error_render=True,
        entity_spec=_fake_entity_spec(),
        handler_raises=BadRequestError(detail="NPI verification failed"),
    )
    client = TestClient(app)
    resp = client.post("/widgets", data={"x": "ok"})

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")


def test_mount_create_successful_post_still_returns_201_with_hx_redirect() -> None:
    """Sanity check: the rerender branch must not interfere with the
    happy path. A valid POST still flows through to the handler and
    returns the standard 201 + HX-Redirect response."""
    app = _build_app(form_error_render=True, entity_spec=_fake_entity_spec())
    client = TestClient(app)
    resp = client.post("/widgets", data={"x": "hello"})

    assert resp.status_code == 201
    assert "HX-Redirect" in resp.headers
    assert resp.headers["Location"].startswith("/widgets/")


# --- helpers --------------------------------------------------------------


async def _fake_handle_get_new_form(
    *, spec, request, requesting_user, kind=None, **_kwargs
):
    """Stand-in for `handle_get_new_form` that returns a minimal
    context dict — enough for `_render_form_with_errors` to layer
    `form_errors` / `form_values` on top without needing a real
    EntitySpec (audit, repos, discriminator registry, …)."""
    return {
        "request": request,
        "current_user": requesting_user,
        "kind": kind,
    }


# --- handle_create (core path) -------------------------------------------


class _AnyRow:
    """Flexible fixture row used by create tests — accepts any kwargs."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, "id"):
            self.id = uuid4()


def _create_fake_repo() -> FakeRepo:
    """Returns a `FakeRepo` extended with `create` / `add_child` /
    `create_polymorphic` for the new framework path."""
    repo = FakeRepo()
    created_rows: list[Any] = []
    added_children: list[tuple[Any, str, Any]] = []
    created_polymorphic: list[tuple[Any, Any, str]] = []
    repo.created_rows = created_rows  # type: ignore[attr-defined]
    repo.added_children = added_children  # type: ignore[attr-defined]
    repo.created_polymorphic = created_polymorphic  # type: ignore[attr-defined]

    async def create(obj):
        if not hasattr(obj, "id"):
            obj.id = uuid4()
        created_rows.append(obj)
        return obj

    async def add_child(parent, collection, child):
        if not hasattr(child, "id"):
            child.id = uuid4()
        added_children.append((parent, collection, child))
        # Mimic the real method: append to parent's collection so
        # snapshots see it.
        bucket = getattr(parent, collection, None)
        if bucket is None:
            bucket = []
            setattr(parent, collection, bucket)
        bucket.append(child)
        return child

    async def create_polymorphic(parent, detail, *, detail_relationship):
        if not hasattr(parent, "id"):
            parent.id = uuid4()
        setattr(parent, detail_relationship, detail)
        created_polymorphic.append((parent, detail, detail_relationship))
        return parent

    repo.create = create  # type: ignore[assignment]
    repo.add_child = add_child  # type: ignore[assignment]
    repo.create_polymorphic = create_polymorphic  # type: ignore[assignment]
    return repo


class _StandardPayload(BaseModel):
    practice_name: str = "Acme"
    location_city: str = "NYC"


@pytest.mark.asyncio
async def test_create_top_level_persists_and_audits():
    """Standard create: instance built from payload + owner column set,
    persisted, audit row written."""
    audit_used = make_audit()
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=audit_used,
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()
    user = make_user()

    created = await handle_create(
        spec,
        payload=_StandardPayload(practice_name="P", location_city="C"),
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert created.practice_name == "P"
    assert created.location_city == "C"
    assert created.owner_id == user.id
    assert len(repo.created_rows) == 1
    assert len(audit_repo.calls) == 1
    assert audit_repo.calls[0]["action"] == audit_used.create


@pytest.mark.asyncio
async def test_create_top_level_without_owner_attr():
    """When `owner_attr=None` (e.g. users — resource IS the user) the
    framework doesn't try to set an owner column."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        owner_attr=None,
        audit=make_audit(),
    )
    repo = _create_fake_repo()
    user = make_user()

    created = await handle_create(
        spec,
        payload=_StandardPayload(),
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=user,
    )

    # Owner column never assigned (would have been "owner_id" by default).
    assert not hasattr(created, "owner_id")


@pytest.mark.asyncio
async def test_create_subentity_appended_to_parent_and_audited():
    """Owned-subentity create: parent loaded, write_authz on parent,
    child instantiated + appended via `add_child`, audit on child."""
    seen_authz = []

    def authz(obj, user, *, action):
        seen_authz.append((obj, action))

    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        write_authz=authz,
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()
    parent_id = uuid4()
    parent_obj = ParentRow(id=parent_id)
    repo.seed(ps.model, parent_obj)
    audit_repo = FakeAuditRepo()
    user = make_user()

    created = await handle_create(
        spec,
        payload=_StandardPayload(),
        parent_id=parent_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )

    assert len(seen_authz) == 1
    assert seen_authz[0][0] is parent_obj  # against parent
    assert len(repo.added_children) == 1
    assert repo.added_children[0][0] is parent_obj
    assert repo.added_children[0][1] == "parts"  # collection = url_collection
    assert repo.added_children[0][2] is created
    assert len(audit_repo.calls) == 1


@pytest.mark.asyncio
async def test_create_subentity_parent_not_found():
    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()  # empty
    with pytest.raises(NotFoundError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=uuid4(),
            repo=repo,
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_create_subentity_missing_parent_id_raises():
    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    with pytest.raises(ValueError, match="parent"):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=None,
            repo=_create_fake_repo(),
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


# --- Polymorphic create ---------------------------------------------------


@_dc(frozen=True)
class _FixtureKindSpec:
    """Stands in for `PostKindSpec` — just the framework-required attrs."""

    kind: str
    detail_model: type
    detail_fields: tuple[str, ...]
    detail_relationship: str


class _RedKindPayload(BaseModel):
    kind: str
    redness: int = 0


class _BlueKindPayload(BaseModel):
    kind: str
    blueness: int = 0


class _RedDetail:
    def __init__(self, redness: int = 0):
        self.redness = redness


class _BlueDetail:
    def __init__(self, blueness: int = 0):
        self.blueness = blueness


@pytest.mark.asyncio
async def test_create_polymorphic_dispatches_via_discriminator():
    """The payload's `kind` picks the kind_spec; parent has the
    discriminator column set; detail built from kind_spec.detail_fields."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureKindSpec(
                kind="red",
                detail_model=_RedDetail,
                detail_fields=("redness",),
                detail_relationship="red_detail",
            ),
            "blue": _FixtureKindSpec(
                kind="blue",
                detail_model=_BlueDetail,
                detail_fields=("blueness",),
                detail_relationship="blue_detail",
            ),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_AnyRow,
        audit=make_audit(),
        discriminator=registry,
    )
    repo = _create_fake_repo()
    user = make_user()

    created_red = await handle_create(
        spec,
        payload=_RedKindPayload(kind="red", redness=7),
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=user,
    )

    # Parent has discriminator column set + owner.
    assert created_red.kind == "red"
    assert created_red.owner_id == user.id
    # Detail attached at the kind_spec.detail_relationship.
    assert isinstance(created_red.red_detail, _RedDetail)
    assert created_red.red_detail.redness == 7
    assert len(repo.created_polymorphic) == 1

    # And the other kind goes through the same path.
    created_blue = await handle_create(
        spec,
        payload=_BlueKindPayload(kind="blue", blueness=11),
        repo=repo,
        audit_repo=FakeAuditRepo(),
        requesting_user=user,
    )
    assert created_blue.kind == "blue"
    assert created_blue.blue_detail.blueness == 11


# --- Error / edge cases --------------------------------------------------


@pytest.mark.asyncio
async def test_create_no_audit_binding_raises():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=None,
    )
    with pytest.raises(ValueError, match="audit"):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            repo=_create_fake_repo(),
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_create_subentity_write_authz_raises_rolls_back():
    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        write_authz=authz,
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    repo = _create_fake_repo()
    parent_id = uuid4()
    repo.seed(ps.model, ParentRow(id=parent_id))
    audit_repo = FakeAuditRepo()

    with pytest.raises(ForbiddenError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            parent_id=parent_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
        )

    # Nothing added, no audit, no commit.
    assert repo.added_children == []
    assert audit_repo.calls == []
    assert repo.session.commits == 0


# --- make_create_handler factory -----------------------------------------


def test_make_create_handler_top_level_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    handler = make_create_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {
        "payload",
        "repo",
        "audit_repo",
        "requesting_user",
    }


def test_make_create_handler_subentity_includes_parent_id():
    ps = parent_spec()
    spec = EntitySpec(
        name="part",
        url_collection="parts",
        id_param="part_id",
        model=_AnyRow,
        parent=ps,
        audit=make_audit(),
        routes=RouteSet(create=True),
        create_adapter=__import__("pydantic").TypeAdapter(_StandardPayload),
    )
    handler = make_create_handler(spec)
    sig = inspect.signature(handler)
    assert "parent_id" in sig.parameters
    assert "payload" in sig.parameters


def test_make_create_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    handler = make_create_handler(spec)
    assert handler.__name__ == "_handle_create_widget"


# --- payload_authz for create --------------------------------------------


class _StubOrgRepo:
    """Stand-in typed repo passed through `payload_authz_repos`."""


@pytest.mark.asyncio
async def test_create_invokes_payload_authz_with_payload_user_and_repos():
    """Happy path: `payload_authz` is awaited with `payload=`,
    `requesting_user=`, plus the declared typed repos. Create proceeds
    and the audit row is written."""
    audit_used = make_audit()
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=audit_used,
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()
    user = make_user()
    org_repo = _StubOrgRepo()

    seen: list[dict[str, Any]] = []

    async def authz(*, payload, requesting_user, organization_repo):
        seen.append(
            {
                "payload": payload,
                "user": requesting_user,
                "org_repo": organization_repo,
            }
        )

    payload = _StandardPayload(practice_name="P", location_city="C")
    created = await handle_create(
        spec,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
        payload_authz=authz,
        payload_authz_kwargs={"organization_repo": org_repo},
    )

    assert len(seen) == 1
    assert seen[0]["payload"] is payload
    assert seen[0]["user"] is user
    assert seen[0]["org_repo"] is org_repo
    assert created.practice_name == "P"
    assert len(repo.created_rows) == 1
    assert len(audit_repo.calls) == 1
    assert audit_repo.calls[0]["action"] == audit_used.create


@pytest.mark.asyncio
async def test_create_payload_authz_forbidden_aborts_before_model_construction():
    """`payload_authz` raising `ForbiddenError` aborts before the model
    is built — no row created, no audit row written."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()

    async def authz(*, payload, requesting_user):
        raise ForbiddenError(detail="nope")

    with pytest.raises(ForbiddenError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
            payload_authz=authz,
        )

    assert repo.created_rows == []
    assert audit_repo.calls == []


@pytest.mark.asyncio
async def test_create_payload_authz_notfound_propagates():
    """`NotFoundError` raised by `payload_authz` propagates unchanged —
    no swallowing inside the framework."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )

    async def authz(*, payload, requesting_user):
        raise NotFoundError(detail="org gone")

    with pytest.raises(NotFoundError):
        await handle_create(
            spec,
            payload=_StandardPayload(),
            repo=_create_fake_repo(),
            audit_repo=FakeAuditRepo(),
            requesting_user=make_user(),
            payload_authz=authz,
        )


def test_make_create_handler_with_payload_authz_signature():
    """Synthesized create-handler signature includes declared
    `payload_authz_repos` kwargs as typed params."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )

    async def authz(**_kw):  # pragma: no cover
        return None

    handler = make_create_handler(
        spec,
        payload_authz=authz,
        payload_authz_repos=(("organization_repo", _StubOrgRepo),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _StubOrgRepo


# --- after_create hook ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_invokes_after_create_with_row_payload_user_and_repos():
    """Happy path: `after_create` is awaited with `row=`, `payload=`,
    `requesting_user=`, plus the declared typed repos. Audit row is
    written after the hook runs (so any mutations the hook makes are
    captured in the audit `after` snapshot)."""
    audit_used = AuditedResource(
        type="widget",
        # Snapshot reads `practice_name` so the test can prove the
        # hook's mutation lands in the audit `after` row.
        snapshot=lambda obj: {
            "id": str(obj.id),
            "practice_name": obj.practice_name,
        },
        create=AuditAction.CREATE_USER,
        update=AuditAction.UPDATE_USER,
        delete=AuditAction.DELETE_USER,
    )
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=audit_used,
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()
    user = make_user()
    extra_repo = _StubOrgRepo()

    seen: list[dict[str, Any]] = []

    async def hook(*, row, payload, requesting_user, organization_repo):
        seen.append(
            {
                "row": row,
                "payload": payload,
                "user": requesting_user,
                "org_repo": organization_repo,
            }
        )
        # Mutate the row — the audit `after` snapshot fires AFTER this,
        # so the mutation should be captured.
        row.practice_name = "mutated-by-hook"

    payload = _StandardPayload(practice_name="P", location_city="C")
    created = await handle_create(
        spec,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
        after_create=hook,
        after_create_kwargs={"organization_repo": extra_repo},
    )

    assert len(seen) == 1
    assert seen[0]["row"] is created
    assert seen[0]["payload"] is payload
    assert seen[0]["user"] is user
    assert seen[0]["org_repo"] is extra_repo
    assert created.practice_name == "mutated-by-hook"
    assert len(repo.created_rows) == 1
    assert len(audit_repo.calls) == 1
    assert audit_repo.calls[0]["action"] == audit_used.create
    # The audit `after` snapshot reflects the post-hook mutation.
    assert audit_repo.calls[0]["after"]["practice_name"] == "mutated-by-hook"


@pytest.mark.asyncio
async def test_create_skips_after_create_when_not_supplied():
    """`after_create=None` is the default — the create path still works
    end-to-end without it (no audit-row regression for entities that
    don't declare the hook)."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()
    payload = _StandardPayload(practice_name="P", location_city="C")
    created = await handle_create(
        spec,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=make_user(),
    )
    assert created.practice_name == "P"
    assert len(audit_repo.calls) == 1


@pytest.mark.asyncio
async def test_create_after_create_exception_rolls_back_transaction():
    """If `after_create` raises, the `mutate(...)` context manager
    propagates the exception and the audit row is NOT written. The
    persisted row stays in the session (the framework relies on the
    session's exception-rollback path, but the audit row's absence is
    the contract this test pins)."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=_AnyRow,
        audit=make_audit(),
    )
    repo = _create_fake_repo()
    audit_repo = FakeAuditRepo()

    async def hook(*, row, payload, requesting_user):
        raise ValueError("after_create rejected this row")

    payload = _StandardPayload(practice_name="P", location_city="C")
    with pytest.raises(ValueError, match="after_create rejected"):
        await handle_create(
            spec,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=make_user(),
            after_create=hook,
        )
    # No audit row written when the hook raises.
    assert audit_repo.calls == []
