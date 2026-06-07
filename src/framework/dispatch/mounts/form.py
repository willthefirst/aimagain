"""`mount_form` — `GET /<collection>/form` or `GET /<collection>/{id}/form`.

Also owns `handle_get_edit_form`, `make_edit_form_handler`,
`handle_get_new_form`, and `make_new_form_handler` — the generic form
handlers and their factories, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel  # noqa: F401 — re-exported for test compat

from src.framework.access.actor.actor import Actor
from src.framework.dispatch.mounts._common import (
    assert_kind_lock,
    call_handler_with,
)
from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import BadRequestError, NotFoundError
from src.framework.http.responses import APIResponse
from src.framework.persistence.base_repository import BaseRepository

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


def mount_form(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str | None = None,
    on_existing: bool = False,
    query_params: tuple[QueryParam, ...] = (),
) -> None:
    """Mount a form-rendering route.

    ``on_existing=False`` mounts ``GET /<collection>/form`` (create-form,
    no entity loaded).
    ``on_existing=True`` mounts ``GET /<collection>/{<id_param>}/form``
    (edit-form, entity loaded by the handler).

    Template precedence (highest to lowest):
      1. ``template_name`` returned in the handler's context dict (for
         polymorphic resources whose template varies at request time —
         e.g. posts kind-dispatch where ``?kind=`` picks the template).
      2. ``template`` kwarg on this call (the simple two-form case where
         create and edit render different static templates).
      3. ``spec.form_template`` (the spec's default).

    Handler kwargs: ``request``, ``repo``, ``requesting_user``, the
    resource id under ``spec.id_param`` (only when ``on_existing=True``),
    each ``query_params`` entry under its declared name, and any
    typed repos the handler declares (resolved via the registry).
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_form with spec.parent is not supported yet (slice 8 / #253)."
        )
    id_param = spec.id_param
    spec_template = spec.form_template

    path = f"/{{{id_param}}}/form" if on_existing else "/form"
    path_param_names = (id_param,) if on_existing else ()

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        # Resolve template: handler context > per-mount kwarg > spec field.
        # `pop` so the template name doesn't leak into the rendered context.
        resolved_template = (
            context.pop("template_name", None) or template or spec_template
        )
        if resolved_template is None:
            raise RuntimeError(
                f"mount_form for {spec.collection!r} (on_existing={on_existing}) "
                "could not resolve a template — set spec.form_template, "
                "the per-mount `template=` kwarg, or have the handler return "
                "`template_name` in its context."
            )
        return APIResponse.html_response(
            template_name=resolved_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.read_user_dep,
            query_params=query_params,
            path_param_names=path_param_names,
        ),
        response_builder=response_builder,
    )
    router.get(path)(route_fn)


async def handle_get_edit_form(
    spec: EntitySpec,
    *,
    request: Request,
    target_id: UUID,
    repo: BaseRepository,
    requesting_user: Actor,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic edit-form handler driven by `spec`.

    When `extras` is set (threaded in by `make_edit_form_handler` from
    the spec's `form_extras_path`), the callable is invoked with
    ``target=<loaded row>``, ``request``, ``requesting_user``, and any
    typed-repo kwargs declared via `form_extras_repos`. The returned
    dict merges into the form context (last-write-wins, mirroring
    `handle_detail` / `handle_list`)."""
    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
    assert_kind_lock(spec, target)
    if spec.write_authz is not None:
        spec.write_authz(target, requesting_user, action=f"edit this {spec.name}")

    # `edit_heading` mirrors `create_heading` in `handle_get_new_form`:
    # one funnel for the H1 string so the page H1 can't drift from the
    # CTA that opened it. For polymorphic specs the kind is derived
    # from the loaded target row (the spec's `discriminator_value` for
    # kind-locked faces is the same value `_assert_kind_lock` just
    # checked; subset-supertype faces use the row's stored kind).
    from src.framework.rendering.labels import edit_label_for
    from src.framework.rendering.route_urls import url_for_spec

    edit_kind: str | None = None
    if spec.discriminator is not None:
        edit_kind = getattr(target, spec.discriminator.column)

    # `resource_url` / `resource_detail_url` are derivable from the
    # spec + the loaded target — every form-edit template used to set
    # them via two `{% set %}` lines. Inject from the handler so child
    # templates skip the boilerplate; same funnel `edit_heading` uses
    # for the H1.
    context: dict[str, Any] = {
        "request": request,
        spec.name: target,
        "entity_name": spec.name,
        "current_user": requesting_user,
        "edit_heading": edit_label_for(spec, kind=edit_kind),
        "resource_url": url_for_spec(spec),
        "resource_detail_url": url_for_spec(spec, id=target.id),
    }
    # Spec-declared constants (enum labels, schema classes the form
    # references, etc.) — same merge precedence as detail/list.
    if spec.static_context:
        context.update(spec.static_context)
    if spec.discriminator is not None:
        if spec.discriminator_value is not None:
            # Kind-locked face: template defaults via
            # `spec.templates.form_edit` (e.g. `referrals/form_edit.html`).
            # Leave `template_name` unset so the mount layer falls back.
            # `_assert_kind_lock` above already guarantees
            # `target.kind == spec.discriminator_value` so the schema
            # class can be picked unambiguously.
            context["schema"] = spec.update_adapter_class
        else:
            kind = getattr(target, spec.discriminator.column)
            context["template_name"] = spec.discriminator[kind].edit_template

    if extras is not None:
        extras_kwargs = {
            "target": target,
            "request": request,
            "requesting_user": requesting_user,
        }
        if extra_kwargs:
            extras_kwargs.update(extra_kwargs)
        context.update(await extras(**extras_kwargs))

    return context


def make_edit_form_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.mounts._factory import (
        _EDIT_FORM_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(
        spec,
        _EDIT_FORM_SHAPE,
        handle_get_edit_form,
        extras=extras,
        extra_repos=extra_repos,
    )


async def handle_get_new_form(
    spec: EntitySpec,
    *,
    request: Request,
    requesting_user: Actor,
    kind: str | None = None,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic create-form handler driven by `spec`.

    For polymorphic entities (those with a `discriminator`):
      * `kind=None` (no `?kind=` on the URL) → don't set `template_name`,
        so the route falls back to `spec.form_template` and renders the
        picker template (conventionally `<collection>/form_new.html`).
        The picker lists the available kinds; users pick one and round-
        trip back to this handler with `?kind=…`.
      * `kind=<value>` → set `template_name` to the kind's
        `create_template` so the route renders the kind-specific form.
    """
    # `create_heading` is the H1 the generic `views/form_new.html` chrome
    # renders. Computing it here — instead of letting each child template
    # override `{% block current_label %}` — funnels every "Create X"
    # string through one helper (`create_label_for` / its Jinja-global
    # twin `entity_create_label`), so the page H1 and the button that
    # opened it can't drift. The handler-side construction is half of
    # the structural pin (the other half is the Jinja global on the
    # CTAs); pinned by `tests/test_form_chrome_labels.py`.
    from src.framework.rendering.labels import create_label_for
    from src.framework.rendering.route_urls import url_for_spec

    # `resource_url` is derivable from `spec.name` — every form-new
    # template used to set it via a `{% set %}` line. Inject from the
    # handler so child templates skip the boilerplate; same funnel
    # `create_heading` uses for the H1.
    context: dict[str, Any] = {
        "request": request,
        "entity_name": spec.name,
        "current_user": requesting_user,
        "create_heading": create_label_for(spec, kind=kind),
        "resource_url": url_for_spec(spec),
    }
    if spec.static_context:
        context.update(spec.static_context)
    if spec.discriminator is not None:
        if spec.discriminator_value is not None:
            # Kind-locked face: the URL family is bound to one kind, so
            # the picker step is skipped and the template defaults via
            # `spec.templates.form_new` (e.g. `referrals/form_new.html`).
            # Leave `template_name` unset so the mount layer falls back
            # to the spec's default. The form_new template still needs
            # the schema class for `field_for(schema, ...)`.
            context["schema"] = spec.create_adapter_class
        elif kind is not None:
            # Subset-supertype face restricts `?kind=` to its declared
            # subset — a user typing `?kind=<value-outside-subset>` must
            # be rejected, not silently routed to that kind's template.
            if (
                spec.discriminator_values is not None
                and kind not in spec.discriminator_values
            ):
                raise BadRequestError(
                    detail=(
                        f"kind={kind!r} is not one of {spec.name}'s subkinds "
                        f"({list(spec.discriminator_values)!r})"
                    )
                )
            context["template_name"] = spec.discriminator[kind].create_template
        # When `kind is None` on a non-locked supertype, leave
        # `template_name` unset so the route falls through to
        # `spec.form_template` (the picker).
    elif spec.create_adapter_class is not None:
        # Non-polymorphic create forms render fields via
        # `field_for(schema, ...)` (reads `schema.model_fields`); the
        # spec's `create_adapter` is the TypeAdapter wrapper, so we bind
        # the underlying class instead.
        context["schema"] = spec.create_adapter_class

    if extras is not None:
        extras_kwargs = {
            "target": None,
            "request": request,
            "requesting_user": requesting_user,
        }
        if extra_kwargs:
            extras_kwargs.update(extra_kwargs)
        context.update(await extras(**extras_kwargs))

    return context


def make_new_form_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.mounts._factory import (
        _NEW_FORM_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(
        spec,
        _NEW_FORM_SHAPE,
        handle_get_new_form,
        extras=extras,
        extra_repos=extra_repos,
    )
