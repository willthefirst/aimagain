"""`mount_create` — `POST /<collection>`."""

from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request, status

from src.framework.dispatch.mounts._common import (
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
    walk_parent_chain,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.forms import parse_form_to_payload, validate_or_422
from src.framework.http.responses import APIResponse, created_response


def mount_create(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Mount ``POST /<collection>``.

    Parses a form-encoded body via ``spec.create_adapter`` (a Pydantic
    ``TypeAdapter``) and calls the handler with ``payload=``, plus any
    typed deps the handler declares (``repo``, ``audit_repo``,
    ``requesting_user``, any extra repos via the registry). The handler
    is expected to use ``mutate(verb="create")`` so the audit row +
    commit are owned by the context manager.

    Response is ``201 Created`` with ``Location`` and ``HX-Redirect`` set.
    Defaults: ``Location: /<collection>/<new_id>``, ``HX-Redirect`` =
    ``spec.create_redirect(...)`` if set, else ``Location``. The
    ``create_redirect`` callable receives the new id under ``spec.id_param``
    so it can build a per-resource target (e.g. providers redirect to
    ``/clinicians/{id}/form`` after create).

    Requires: ``spec.write_user_dep``, ``spec.create_adapter``.
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_create requires {spec.collection!r} to set write_user_dep."
        )
    if spec.create_adapter is None:
        raise ValueError(
            f"mount_create requires {spec.collection!r} to set create_adapter."
        )

    collection = spec.collection
    id_param = spec.id_param
    create_adapter = spec.create_adapter
    create_redirect = spec.create_redirect

    path = path_segments_under_router(spec, with_id=False)
    parent_id_names = tuple(p[0] for p in parent_path_param_pairs(spec))

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        # Parse + validate split so the raw payload survives validation
        # failure: when `spec.form_error_render` opts in, an HX-Request
        # client gets the form template re-rendered with the typed values
        # still in place rather than a JSON 422 with nowhere to land.
        payload_dict = await parse_form_to_payload(request)
        try:
            kwargs["payload"] = validate_or_422(create_adapter, payload_dict)
        except HTTPException as exc:
            if (
                exc.status_code == 422
                and spec.form_error_render
                and request.headers.get("HX-Request") == "true"
            ):
                return await _render_form_with_errors(
                    spec=spec,
                    request=request,
                    requesting_user=kwargs.get("requesting_user"),
                    payload_dict=payload_dict,
                    errors=exc.detail,
                )
            raise
        created = await call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in parent_id_names}
        # Default Location is the canonical resource URL — for a top-level
        # resource that's /<collection>/{id}; for a sub-resource we point
        # at the parent because the spec doesn't have a "list children"
        # canonical URL convention. Per-resource overrides via
        # `create_redirect` handle the HX-Redirect target.
        if spec.parent is None:
            location = f"/{collection}/{created.id}"
        else:
            top = walk_parent_chain(spec)[0]
            top_id = path_kwargs[top.id_param]
            location = f"/{top.collection}/{top_id}"
        if create_redirect is not None:
            hx = create_redirect(**path_kwargs, **{id_param: created.id})
        else:
            hx = location
        return created_response(id=created.id, location=location, hx_redirect=hx)

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=create_adapter,
            path_param_names=parent_id_names,
        ),
        response_builder=response_builder,
    )
    router.post(path, status_code=status.HTTP_201_CREATED)(route_fn)


async def _render_form_with_errors(
    *,
    spec: ResourceSpec,
    request: Request,
    requesting_user: Any,
    payload_dict: dict,
    errors: Any,
) -> Any:
    """Re-render the spec's form_new template with field-level errors.

    Called by `mount_create` on a 422 from `validate_or_422` when the
    spec has opted in via `form_error_render=True` and the request is
    an HX-Request. The form template receives:

      - `form_errors`: a `{field_name: first_error_message}` dict built
        from the 422 detail list. Discriminated-union locs (`("<kind>",
        "<field>")`) are stripped of the kind prefix so the dict keys
        match the form field names; the macro layer reads
        `error=errors.get(name)` and auto-emits `aria-invalid="true"`
        + the inline message.
      - `form_values`: the raw submitted payload dict, so controls
        prefill from what the user typed instead of resetting.

    The originating `EntitySpec` (carried as `spec.entity_spec` by
    `to_resource_spec()`) drives the kind-aware template lookup via
    `handle_get_new_form` — same template-resolution path the form_new
    GET handler uses, so the re-render is structurally indistinguishable
    from a fresh GET aside from the injected `form_errors`/`form_values`.

    Returns a 200-OK HTML response; the form's
    `hx-target="this" hx-swap="outerHTML"` swaps it in place. Status is
    200 (not 422) because the default HTMX response-handling table only
    swaps 2xx — non-HTMX clients and the JSON-422 contract are
    untouched (this branch is gated on `HX-Request: true`).
    """
    from src.framework.dispatch.handlers import handle_get_new_form

    entity_spec = spec.entity_spec
    if entity_spec is None:
        # `form_error_render=True` without a back-reference to the
        # EntitySpec means a synthetic ResourceSpec opted in but didn't
        # populate `entity_spec`. Bail to the original 422 rather than
        # 500 on a template lookup.
        raise HTTPException(status_code=422, detail=errors)

    kind = payload_dict.get("kind") if entity_spec.discriminator is not None else None
    # `handle_get_new_form` builds the same context the form_new GET
    # handler would assemble — current_user, schema, create_heading,
    # resource_url, and (for subset-supertype/whole-supertype) the
    # kind-specific template_name. Reusing it keeps the re-render
    # context identical to a fresh GET so child templates can't drift.
    context = await handle_get_new_form(
        spec=entity_spec,
        request=request,
        requesting_user=requesting_user,
        kind=kind,
    )
    # `form_errors` is a per-field dict for the macro `error=` param.
    # The detail list is `[{loc: tuple, msg: str, type: str}, ...]`.
    # For discriminated-union adapters Pydantic prefixes `loc` with the
    # kind (e.g. `("clinician_opening", "age_groups")`), so strip a
    # leading segment that matches the submitted kind before reducing
    # to the field name. Keep the first message per field so repeated
    # nested errors on the same field don't clobber render order.
    form_errors: dict[str, str] = {}
    if isinstance(errors, list):
        for err in errors:
            loc = err.get("loc") if isinstance(err, dict) else None
            msg = err.get("msg") if isinstance(err, dict) else None
            if not loc or not msg:
                continue
            loc_seq = list(loc) if isinstance(loc, (tuple, list)) else [loc]
            if kind is not None and loc_seq and loc_seq[0] == kind:
                loc_seq = loc_seq[1:]
            if not loc_seq:
                continue
            field = loc_seq[0]
            form_errors.setdefault(str(field), str(msg))
    context["form_errors"] = form_errors
    context["form_values"] = payload_dict
    template_name = context.pop("template_name", None) or entity_spec.templates.form_new
    if template_name is None:
        # Defensive: a spec that opted into `form_error_render` without
        # a resolvable form_new template would silently 500 — better to
        # fall through to the original 422 so the caller sees the
        # validation failure rather than a template error.
        raise HTTPException(status_code=422, detail=errors)
    return APIResponse.html_response(
        template_name=template_name,
        context=context,
        request=request,
        current_user=requesting_user,
    )
