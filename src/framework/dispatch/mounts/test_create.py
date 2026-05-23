"""Tests for `mount_create` — focus on the form-error-rerender branching.

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

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter

from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts.create import build_form_errors_dict, mount_create

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
) -> FastAPI:
    """Synthetic FastAPI app with one `POST /widgets` route mounted via
    `mount_create`. Stub deps return predictable sentinels so handler
    invocation can be observed without a real DB / audit layer.
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

    def stub(template_name, context, request, *, current_user=None):
        calls.append(
            {
                "template_name": template_name,
                "context": context,
                "current_user": current_user,
            }
        )
        return Response(content=html, media_type="text/html", status_code=200)

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
    failure → renderer is called (returns 200), no 422 surfaces."""
    app = _build_app(form_error_render=True, entity_spec=_fake_entity_spec())
    renderer = _stub_renderer_returning("<form>rendered</form>")
    with (
        patch(
            "src.framework.dispatch.mounts.create.APIResponse.html_response",
            new=renderer,
        ),
        patch(
            "src.framework.dispatch.handlers.handle_get_new_form",
            new=_fake_handle_get_new_form,
        ),
    ):
        client = TestClient(app)
        # POST with no `x` → 422 from validation; HX-Request opts into
        # the rerender branch.
        resp = client.post("/widgets", data={}, headers={"HX-Request": "true"})

    assert resp.status_code == 200
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
        "src.framework.dispatch.mounts.create.APIResponse.html_response",
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
        "src.framework.dispatch.mounts.create.APIResponse.html_response",
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
