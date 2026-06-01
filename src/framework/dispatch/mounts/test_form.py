"""Tests for form handlers in `mounts/form.py`.

Covers `handle_get_edit_form`, `make_edit_form_handler`,
`handle_get_new_form`, `make_new_form_handler`, and form-extras integration.

Moved from `src/framework/dispatch/test_handlers.py`.
"""

import inspect
from dataclasses import dataclass as _dc
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel as _BaseModel

from src.framework.dispatch.entity_spec import EntitySpec, RouteSet
from src.framework.dispatch.mounts.conftest import (
    FakeRepo,
    FixtureRow,
    make_audit,
    make_user,
    top_level_spec,
)
from src.framework.dispatch.mounts.form import (
    handle_get_edit_form,
    handle_get_new_form,
    make_edit_form_handler,
    make_new_form_handler,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.persistence.polymorphic import DiscriminatorRegistry


def _request_stub():
    return SimpleNamespace()


# --- Edit-form handler fixtures ------------------------------------------


@_dc(frozen=True)
class _FixtureEditKindSpec:
    """Stands in for `PostKindSpec` — only `edit_template` is load-bearing."""

    edit_template: str


class _PolyRow:
    """Stand-in polymorphic parent: has an `id` and a `kind` column."""

    def __init__(self, id: UUID, kind: str):
        self.id = id
        self.kind = kind


# --- handle_get_edit_form happy paths ------------------------------------


@pytest.mark.asyncio
async def test_edit_form_top_level_happy_path():
    """Load target, no write_authz, returns context with entity under `spec.name`."""
    spec = top_level_spec(write_authz=None)
    repo = FakeRepo()
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo.seed(FixtureRow, target)
    user = make_user()
    request = _request_stub()

    context = await handle_get_edit_form(
        spec,
        request=request,
        target_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert context["request"] is request
    assert context["widget"] is target  # bound under spec.name
    assert context["current_user"] is user
    assert "template_name" not in context


@pytest.mark.asyncio
async def test_edit_form_invokes_write_authz_against_target():
    """`write_authz` is called against the target with action text."""
    calls = []

    def authz(obj, user, *, action):
        calls.append((obj, user, action))

    spec = top_level_spec(write_authz=authz)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)
    user = make_user()

    await handle_get_edit_form(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert len(calls) == 1
    assert calls[0][0] is target
    assert calls[0][1] is user
    assert "edit this widget" in calls[0][2]


@pytest.mark.asyncio
async def test_edit_form_target_not_found_raises_not_found():
    spec = top_level_spec()
    repo = FakeRepo()
    with pytest.raises(NotFoundError):
        await handle_get_edit_form(
            spec,
            request=_request_stub(),
            target_id=uuid4(),
            repo=repo,
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_edit_form_write_authz_raises_propagates():
    def authz(obj, user, *, action):
        raise ForbiddenError(detail="nope")

    spec = top_level_spec(write_authz=authz)
    target_id = uuid4()
    repo = FakeRepo()
    repo.seed(FixtureRow, FixtureRow(id=target_id))
    with pytest.raises(ForbiddenError):
        await handle_get_edit_form(
            spec,
            request=_request_stub(),
            target_id=target_id,
            repo=repo,
            requesting_user=make_user(),
        )


@pytest.mark.asyncio
async def test_edit_form_polymorphic_returns_kind_template():
    """For polymorphic entities, the context carries `template_name`
    derived from the discriminator-registry entry's `edit_template`."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureEditKindSpec(edit_template="paintings/edit_red.html"),
            "blue": _FixtureEditKindSpec(edit_template="paintings/edit_blue.html"),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=make_audit(),
        discriminator=registry,
    )
    target_id = uuid4()
    target = _PolyRow(id=target_id, kind="blue")
    repo = FakeRepo()
    repo.seed(_PolyRow, target)

    context = await handle_get_edit_form(
        spec,
        request=_request_stub(),
        target_id=target_id,
        repo=repo,
        requesting_user=make_user(),
    )

    assert context["painting"] is target
    assert context["template_name"] == "paintings/edit_blue.html"


# --- make_edit_form_handler factory --------------------------------------


def test_make_edit_form_handler_signature():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
    )
    handler = make_edit_form_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {"request", "widget_id", "repo", "requesting_user"}


def test_make_edit_form_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
    )
    handler = make_edit_form_handler(spec)
    assert handler.__name__ == "_handle_get_widget_edit_form"


@pytest.mark.asyncio
async def test_make_edit_form_handler_delegates_to_handle_get_edit_form():
    """The factory-built handler invokes `handle_get_edit_form` with the
    spec bound and the URL/dep-resolved kwargs forwarded."""
    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)
    user = make_user()
    request = SimpleNamespace()

    handler = make_edit_form_handler(spec)
    context = await handler(
        request=request,
        widget_id=target_id,
        repo=repo,
        requesting_user=user,
    )

    assert context["widget"] is target
    assert context["current_user"] is user


# --- handle_get_new_form happy paths -------------------------------------


class _FormSchema(_BaseModel):
    name: str = ""


@_dc(frozen=True)
class _FixtureNewKindSpec:
    """Stands in for `PostKindSpec` — only `create_template` is load-bearing."""

    create_template: str


@pytest.mark.asyncio
async def test_new_form_top_level_happy_path():
    """Non-polymorphic: returns request + current_user + schema class."""
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = make_user()
    request = SimpleNamespace()

    context = await handle_get_new_form(spec, request=request, requesting_user=user)

    assert context["request"] is request
    assert context["current_user"] is user
    assert context["schema"] is _FormSchema
    assert "template_name" not in context


@pytest.mark.asyncio
async def test_new_form_merges_static_context():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
        static_context={"LABELS": {"a": "A"}},
    )

    context = await handle_get_new_form(
        spec, request=_request_stub(), requesting_user=make_user()
    )

    assert context["LABELS"] == {"a": "A"}


@pytest.mark.asyncio
async def test_new_form_polymorphic_uses_kind_create_template():
    """Polymorphic: template_name comes from `spec.discriminator[kind].create_template`."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureNewKindSpec(create_template="paintings/new_red.html"),
            "blue": _FixtureNewKindSpec(create_template="paintings/new_blue.html"),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=make_audit(),
        discriminator=registry,
    )

    context = await handle_get_new_form(
        spec,
        request=_request_stub(),
        requesting_user=make_user(),
        kind="blue",
    )

    assert context["template_name"] == "paintings/new_blue.html"
    assert "schema" not in context


@pytest.mark.asyncio
async def test_new_form_polymorphic_no_kind_leaves_template_unset():
    """Polymorphic + `kind=None`: handler does NOT set `template_name`."""
    registry = DiscriminatorRegistry(
        column="kind",
        specs={
            "red": _FixtureNewKindSpec(create_template="paintings/new_red.html"),
            "blue": _FixtureNewKindSpec(create_template="paintings/new_blue.html"),
        },
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=make_audit(),
        discriminator=registry,
    )

    context = await handle_get_new_form(
        spec, request=_request_stub(), requesting_user=make_user(), kind=None
    )

    assert "template_name" not in context


# --- make_new_form_handler factory ----------------------------------------


def test_make_new_form_handler_signature_non_polymorphic():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    handler = make_new_form_handler(spec)
    sig = inspect.signature(handler)
    assert set(sig.parameters) == {"request", "requesting_user"}


def test_make_new_form_handler_signature_polymorphic_includes_kind():
    registry = DiscriminatorRegistry(
        column="kind",
        specs={"red": _FixtureNewKindSpec(create_template="x.html")},
    )
    spec = EntitySpec(
        name="painting",
        url_collection="paintings",
        id_param="painting_id",
        model=_PolyRow,
        audit=make_audit(),
        discriminator=registry,
    )
    handler = make_new_form_handler(spec)
    sig = inspect.signature(handler)
    assert "kind" in sig.parameters
    assert "repo" not in sig.parameters


def test_make_new_form_handler_name_includes_entity():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    handler = make_new_form_handler(spec)
    assert handler.__name__ == "_handle_get_widget_new_form"


@pytest.mark.asyncio
async def test_make_new_form_handler_delegates_to_handle_get_new_form():
    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = make_user()
    request = SimpleNamespace()

    handler = make_new_form_handler(spec)
    context = await handler(request=request, requesting_user=user)

    assert context["schema"] is _FormSchema
    assert context["current_user"] is user


# --- form_extras (create + edit) -----------------------------------------


@pytest.mark.asyncio
async def test_new_form_invokes_form_extras_with_target_none():
    """`handle_get_new_form` calls `extras` with `target=None` and merges
    the returned dict into the context."""
    captured: dict[str, Any] = {}

    async def extras(**kwargs):
        captured.update(kwargs)
        return {"orgs": ["a", "b"]}

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )
    user = make_user()
    request = SimpleNamespace()

    context = await handle_get_new_form(
        spec,
        request=request,
        requesting_user=user,
        extras=extras,
        extra_kwargs={"organization_repo": "REPO_SENTINEL"},
    )

    assert captured["target"] is None
    assert captured["request"] is request
    assert captured["requesting_user"] is user
    assert captured["organization_repo"] == "REPO_SENTINEL"
    assert context["orgs"] == ["a", "b"]


@pytest.mark.asyncio
async def test_edit_form_invokes_form_extras_with_target_row():
    """`handle_get_edit_form` calls `extras` with the loaded row bound to
    `target` and merges the returned dict into the context."""
    captured: dict[str, Any] = {}

    async def extras(**kwargs):
        captured.update(kwargs)
        return {"orgs": ["x"]}

    spec = top_level_spec(write_authz=None)
    target_id = uuid4()
    target = FixtureRow(id=target_id)
    repo = FakeRepo()
    repo.seed(FixtureRow, target)
    user = make_user()
    request = SimpleNamespace()

    context = await handle_get_edit_form(
        spec,
        request=request,
        target_id=target_id,
        repo=repo,
        requesting_user=user,
        extras=extras,
        extra_kwargs={"organization_repo": "REPO_SENTINEL"},
    )

    assert captured["target"] is target
    assert captured["request"] is request
    assert captured["requesting_user"] is user
    assert captured["organization_repo"] == "REPO_SENTINEL"
    assert context["orgs"] == ["x"]
    assert context["widget"] is target


def test_make_edit_form_handler_includes_extra_repos_in_signature():
    """`extra_repos=` declared on the factory adds typed-repo kwargs."""

    class _RepoMarker:
        pass

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
    )

    async def extras(**_):
        return {}

    handler = make_edit_form_handler(
        spec,
        extras=extras,
        extra_repos=(("organization_repo", _RepoMarker),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _RepoMarker


def test_make_new_form_handler_includes_extra_repos_in_signature():
    class _RepoMarker:
        pass

    spec = EntitySpec(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=FixtureRow,
        audit=make_audit(),
        create_adapter=_FormSchema,
        routes=RouteSet(create=True, form_new=True),
    )

    async def extras(**_):
        return {}

    handler = make_new_form_handler(
        spec,
        extras=extras,
        extra_repos=(("organization_repo", _RepoMarker),),
    )
    sig = inspect.signature(handler)
    assert "organization_repo" in sig.parameters
    assert sig.parameters["organization_repo"].annotation is _RepoMarker
