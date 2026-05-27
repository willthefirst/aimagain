"""`mount_related_list` — `GET /<parent>/{parent_id}/<child>`."""

from typing import Any, Awaitable, Callable

from fastapi import Request

from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import APIResponse


def mount_related_list(
    router: Any,
    parent_spec: ResourceSpec,
    child_spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str,
    singleton_alias: tuple[str, Callable[..., Any]] | None = None,
) -> None:
    """Mount ``GET /<parent.collection>/{<parent.id_param>}/<child.collection>``.

    A scoped read of children belonging to a parent — e.g.
    ``GET /users/{user_id}/clinicians`` lists the clinician directory
    entries owned by a user.

    Handler kwargs: ``request``, the parent id under
    ``parent_spec.id_param`` (e.g. ``user_id=...``), ``repo`` (the
    *child's* repo, since the handler returns children),
    ``requesting_user``, and any typed repos the handler declares
    (resolved via the type registry). Returns a context dict; the
    mount renders ``template``.

    ``template`` is a per-mount kwarg (not on the spec) because related-list
    templates often live in the parent's namespace
    (``users/clinicians_list.html``, not ``clinicians/list.html``) — making
    it a per-mount knob keeps both the parent and child specs reusable.

    Auth follows the parent's ``read_user_dep`` (the URL is rooted at the
    parent so its read-auth governs). If the parent is public
    (``read_user_dep=None``), the route is public too.

    ``singleton_alias=("me", current_active_user)`` additionally mounts
    ``GET /<parent.collection>/<alias>/<child.collection>`` (e.g.
    ``/users/me/clinicians``). The parent id is sourced from
    ``current_active_user().id`` and passed to the handler — same handler,
    same template, same response. The alias is purely an id-derivation
    convenience.
    """
    if not template:
        raise ValueError(
            "mount_related_list requires `template=` — related-list "
            "templates aren't on the spec because they typically live in "
            "the parent's namespace."
        )
    parent_id_param = parent_spec.id_param
    path = f"/{{{parent_id_param}}}/{child_spec.collection}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    # The route renders children, so the synthesis hands the handler the
    # *child's* repo under `repo`. The parent-id path param is bound by
    # name from the URL. Auth follows the *parent's* read user dep.
    route_fn = synthesize_route_fn(
        handler=handler,
        spec=child_spec,
        options=SynthOptions(
            user_dep=parent_spec.read_user_dep,
            path_param_names=(parent_id_param,),
        ),
        response_builder=response_builder,
    )

    if singleton_alias is not None:
        alias_segment, session_dep = singleton_alias
        alias_path = f"/{alias_segment}/{child_spec.collection}"

        async def alias_response_builder(*, handler, handler_kwarg_names, kwargs):
            session_user = kwargs["__session_user__"]
            kwargs = {
                **kwargs,
                parent_id_param: session_user.id,
                "requesting_user": session_user,
            }
            return await response_builder(
                handler=handler, handler_kwarg_names=handler_kwarg_names, kwargs=kwargs
            )

        alias_route_fn = synthesize_route_fn(
            handler=handler,
            spec=child_spec,
            options=SynthOptions(
                user_dep=None,
                handler_supplied_names=(parent_id_param, "requesting_user"),
                extra_static_deps=(("__session_user__", session_dep),),
            ),
            response_builder=alias_response_builder,
        )
        router.get(alias_path)(alias_route_fn)

    router.get(path)(route_fn)
