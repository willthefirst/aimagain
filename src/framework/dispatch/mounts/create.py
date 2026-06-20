"""`mount_create` — `POST /<collection>`.

Also owns `handle_create` and `make_create_handler` — the generic
create handler and its factory, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from src.framework.access.actor.actor import Actor
from src.framework.audit.core import mutate
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.mounts._common import (
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
    walk_parent_chain,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import NotFoundError
from src.framework.http.form_rerender import form_rerender
from src.framework.http.forms import parse_form_to_payload, validate_or_422
from src.framework.http.responses import created_response
from src.framework.persistence.base_repository import BaseRepository

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec

# Generic form-level summary shown on a validation (422) re-render when
# the caller didn't supply a more specific banner. The per-field errors
# carry the detail; this banner exists so a failed submit is announced
# at the top of the form (and to screen readers via the banner's
# `role="alert"`) instead of only highlighting fields that may be
# scrolled off-screen above the submit button.
_VALIDATION_SUMMARY_BANNER = "Please fix the highlighted fields below, then resubmit."


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
    so it can build a per-resource target (e.g. clinicians redirect to
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
        try:
            created = await call_handler_with(handler, handler_kwarg_names, kwargs)
        except HTTPException as exc:
            # Handler-raised 400s (e.g. the NPPES verification gate in
            # the clinician/org `after_create` hooks) get the same
            # in-place HTMX form re-render the 422 path uses, with the
            # handler's `detail` carried as a single form-level banner.
            # Non-HTMX clients still see the raw 400 JSON.
            if (
                exc.status_code == 400
                and spec.form_error_render
                and request.headers.get("HX-Request") == "true"
            ):
                banner = (
                    exc.detail if isinstance(exc.detail, str) else "Could not create."
                )
                return await _render_form_with_errors(
                    spec=spec,
                    request=request,
                    requesting_user=kwargs.get("requesting_user"),
                    payload_dict=payload_dict,
                    errors=[],
                    form_banner=banner,
                    status_code=400,
                )
            raise
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


def build_form_errors_dict(errors: Any, *, kind: str | None = None) -> dict[str, str]:
    """Collapse a 422 detail list into a `{field_name: first_message}` dict.

    Input shape matches `validate_or_422`'s output:
    `[{loc: tuple, msg: str, type: str}, ...]`. For discriminated-union
    adapters Pydantic prefixes `loc` with the kind discriminator (e.g.
    `("clinician_opening", "age_groups")`); when `kind` is supplied and
    matches the first `loc` segment, the prefix is stripped so the dict
    keys land at the field name the form macros look up.

    The first message wins per field — repeated nested errors on the
    same field don't clobber render order. Malformed entries (no `loc`,
    no `msg`, prefix-only locs) are skipped silently rather than raising,
    so a future Pydantic shape change degrades to "no inline error"
    instead of 500.
    """
    out: dict[str, str] = {}
    if not isinstance(errors, list):
        return out
    for err in errors:
        if not isinstance(err, dict):
            continue
        loc = err.get("loc")
        msg = err.get("msg")
        if not loc or not msg:
            continue
        loc_seq = list(loc) if isinstance(loc, (tuple, list)) else [loc]
        if kind is not None and loc_seq and loc_seq[0] == kind:
            loc_seq = loc_seq[1:]
        if not loc_seq:
            continue
        field = loc_seq[0]
        out.setdefault(str(field), str(msg))
    return out


async def _render_form_with_errors(
    *,
    spec: ResourceSpec,
    request: Request,
    requesting_user: Any,
    payload_dict: dict,
    errors: Any,
    form_banner: str | None = None,
    status_code: int = 422,
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
    from src.framework.dispatch.mounts.form import handle_get_new_form

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
    template_name = context.pop("template_name", None) or entity_spec.templates.form_new
    if template_name is None:
        # Defensive: a spec that opted into `form_error_render` without
        # a resolvable form_new template would silently 500 — better to
        # fall through to the original 422 so the caller sees the
        # validation failure rather than a template error.
        raise HTTPException(status_code=422, detail=errors)
    # Render *just the form fragment*, not the full page. HTMX swaps
    # the response into the form via `hx-target="this" hx-swap="outerHTML"`;
    # feeding it a full page (with `<html>`, header chrome, etc.) would
    # nest the entire page inside the form slot — visually broken.
    # Convention: full template `<dir>/<name>.html` has a fragment at
    # `<dir>/_<name>_fragment.html`. If the fragment doesn't exist the
    # render falls back to the full template (visibly-broken nesting,
    # surfaced by the per-form route smoke's no-chrome assertion).
    #
    # `status_code=422` because the body was syntactically parseable
    # but failed validation — RFC 9110 §15.5.21. Form fragments
    # declare `hx-target-4xx="this"` so the `response-targets` htmx
    # extension swaps on the 422 (the default response handler only
    # swaps on 2xx).
    fragment_name = _fragment_template_name(template_name)
    field_errors = build_form_errors_dict(errors, kind=kind)
    # When the caller didn't pin a specific banner (the 422 validation
    # path) but there *are* field errors, fall back to the generic
    # summary so the failure is visible at the top of the form. The 400
    # business-rule path always passes its own `form_banner`, so this
    # never overrides a caller-supplied message.
    banner = form_banner
    if banner is None and field_errors:
        banner = _VALIDATION_SUMMARY_BANNER
    return form_rerender(
        request=request,
        template_name=fragment_name,
        context=context,
        field_errors=field_errors,
        form_banner=banner,
        values=payload_dict,
        current_user=requesting_user,
        status_code=status_code,
    )


def _fragment_template_name(full_path: str) -> str:
    """Convert a full form-page template path to its fragment sibling.

    `posts/new_clinician_opening.html` →
    `posts/_new_clinician_opening_fragment.html`

    The fragment is a thin Jinja template that calls the same form
    macro the full page does, with no `extends` — so rendering it
    produces just the `<form>` element, the right shape for an HTMX
    `outerHTML` swap that replaces the form in place.

    Failure mode if the fragment file doesn't exist: Jinja raises
    `TemplateNotFound` on render. That's intentional — surfacing the
    missing-fragment as a 500 makes the bug discoverable, vs. silently
    nesting the chrome.
    """
    import os

    dirname, basename = os.path.split(full_path)
    name, ext = os.path.splitext(basename)
    return os.path.join(dirname, f"_{name}_fragment{ext}")


async def handle_create(
    spec: EntitySpec,
    *,
    payload: BaseModel,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_kwargs: dict[str, Any] | None = None,
    after_create: Callable[..., Awaitable[None]] | None = None,
    after_create_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Generic create handler driven by `spec`.

    `payload_authz` (if supplied) is invoked AFTER the parent row has
    been loaded and `write_authz` has run on it (if applicable), and
    BEFORE the payload is used to build the model. The callable is
    expected to raise `ForbiddenError` / `NotFoundError` on rejection;
    `payload_authz_kwargs` supplies any spec-declared typed repo kwargs.
    See `EntitySpec.payload_authz_path` for the contract.

    `after_create` (if supplied) is invoked AFTER the row has been
    persisted (it has an id) and BEFORE the audit `after`-snapshot is
    taken. Use it to mutate the row's server-controlled columns based
    on the payload, OR to do side effects in the same transaction
    (e.g. record a `Verification` event). The hook receives `row=`,
    `payload=`, `requesting_user=`, and `**after_create_kwargs`. See
    `EntitySpec.after_create_path` for the contract."""
    if spec.audit is None:
        raise ValueError(
            f"handle_create: spec {spec.name!r} has no audit binding; "
            "create operations must be audited."
        )

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_create: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"create this {spec.name}")
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        child = spec.model(**payload.model_dump())
        created = await repo.add_child(parent, spec.url_collection, child)

    elif spec.discriminator is not None:
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        kind = payload.kind
        kind_spec = spec.discriminator[kind]
        # Read detail fields off the serialized dump, not via
        # ``getattr``, so wire-flat / schema-nested fields (e.g. the
        # post-#451 ``location: Location`` value object on
        # :class:`ReferralCreate`, which serializes back to flat
        # ``location_city`` / ``location_state`` / ``location_zip`` keys
        # via ``flatten_location_on_dump``) line up with the ORM
        # model's flat columns enumerated in ``detail_fields``.
        dump = payload.model_dump()
        detail = kind_spec.detail_model(
            **{f: dump[f] for f in kind_spec.detail_fields if f in dump}
        )
        parent_obj = spec.model(**{spec.discriminator.column: kind})
        if spec.owner_attr is not None:
            setattr(parent_obj, spec.owner_attr, requesting_user.id)
        created = await repo.create_polymorphic(
            parent_obj, detail, detail_relationship=kind_spec.detail_relationship
        )

    else:
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        # Inline-child collections (e.g. clinician's licensures /
        # educations / certifications) come in on the payload alongside
        # the parent's own fields. Exclude them from the parent
        # constructor, persist the parent, then append each child via
        # `repo.add_child` so the in-memory state stays coherent for
        # the audit after-snapshot. Empty `spec.children` is the common
        # case (most entities have no inline children) and the loop is
        # a no-op.
        inline_collections = tuple(c.url_collection for c in spec.children)
        parent_fields = payload.model_dump(exclude=set(inline_collections))
        instance = spec.model(**parent_fields)
        if spec.owner_attr is not None:
            setattr(instance, spec.owner_attr, requesting_user.id)
        created = await repo.create(instance)
        for child_spec in spec.children:
            for item in getattr(payload, child_spec.url_collection, []) or []:
                await repo.add_child(
                    created,
                    child_spec.url_collection,
                    child_spec.model(**item.model_dump()),
                )

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=spec.audit,
        verb="create",
    ):
        # `after_create` runs inside the `mutate(...)` block — after
        # persistence (so the row has an id) and before the audit
        # `after`-snapshot is taken (so any row mutations the hook
        # makes are reflected in the snapshot). Raises propagate; the
        # context manager rolls back the transaction without writing
        # the audit row.
        if after_create is not None:
            await after_create(
                row=created,
                payload=payload,
                requesting_user=requesting_user,
                **(after_create_kwargs or {}),
            )
    return created


def make_create_handler(
    spec: EntitySpec,
    *,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
    after_create: Callable[..., Awaitable[None]] | None = None,
    after_create_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.mounts._factory import (
        _CREATE_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(
        spec,
        _CREATE_SHAPE,
        handle_create,
        payload_authz=payload_authz,
        payload_authz_repos=payload_authz_repos,
        after_create=after_create,
        after_create_repos=after_create_repos,
    )
