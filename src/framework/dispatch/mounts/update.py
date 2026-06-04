"""`mount_update` — `PATCH /<collection>/{<id_param>}`.

Also owns `handle_update` and `make_update_handler` — the generic
update handler and its factory, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.framework.actor import Actor
from src.framework.audit.core import mutate
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.mounts._common import (
    assert_kind_lock,
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import BadRequestError, NotFoundError
from src.framework.http.forms import parse_and_validate_form
from src.framework.http.responses import updated_response
from src.framework.persistence.base_repository import BaseRepository

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


def mount_update(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Mount ``PATCH /<collection>/{<id_param>}``.

    Parses a form-encoded body via ``spec.update_adapter`` and calls the
    handler with the resource id (under ``spec.id_param``), ``payload=``,
    and any typed deps the handler declares. Handler uses
    ``mutate(verb="update")``.

    Response is ``200 OK`` with body = ``spec.read_to_dict(updated)`` (if
    set, else empty body) and ``HX-Redirect`` =
    ``spec.update_redirect(...)`` (if set, else ``f"/<collection>/<id>"``).

    Requires: ``spec.write_user_dep``, ``spec.update_adapter``.
    ``read_to_dict`` is optional but conventional — clients often want
    the new state without a follow-up GET.
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_update requires {spec.collection!r} to set write_user_dep."
        )
    if spec.update_adapter is None:
        raise ValueError(
            f"mount_update requires {spec.collection!r} to set update_adapter."
        )

    collection = spec.collection
    id_param = spec.id_param
    update_adapter = spec.update_adapter
    update_redirect = spec.update_redirect
    read_to_dict = spec.read_to_dict

    path = path_segments_under_router(spec, with_id=True)
    parent_id_names = tuple(p[0] for p in parent_path_param_pairs(spec))

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_form(request, update_adapter)
        updated = await call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in (*parent_id_names, id_param)}
        body = read_to_dict(updated) if read_to_dict else None
        if update_redirect is not None:
            hx = update_redirect(**path_kwargs)
        else:
            hx = f"/{collection}/{updated.id}"
        return updated_response(body=body, hx_redirect=hx)

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=update_adapter,
            path_param_names=(*parent_id_names, id_param),
        ),
        response_builder=response_builder,
    )
    router.patch(path)(route_fn)


async def handle_update(
    spec: EntitySpec,
    *,
    target_id: UUID,
    payload: BaseModel,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_kwargs: dict[str, Any] | None = None,
    after_update: Callable[..., Awaitable[None]] | None = None,
    after_update_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Generic update handler driven by `spec`.

    `payload_authz` (if supplied) is invoked AFTER the target 404 check
    and AFTER `write_authz` has run on parent-or-target, and BEFORE the
    payload is consumed (discriminator dispatch / patch). When the
    target 404s, the hook is never called — the 404 fires first. See
    `EntitySpec.payload_authz_path` for the contract.

    `after_update` (if supplied) is invoked AFTER the row is patched and
    BEFORE the audit `after`-snapshot, inside the same `mutate(...)`
    block (raises roll back the whole update). It receives `row=`,
    `payload=`, `requesting_user=`, `changed_fields=` (the set of column
    names whose value actually changed) and `**after_update_kwargs`. Only
    fires on the non-polymorphic update path — see
    `EntitySpec.after_update_path`."""
    if spec.audit is None:
        raise ValueError(
            f"handle_update: spec {spec.name!r} has no audit binding; "
            "update operations must be audited."
        )

    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
    assert_kind_lock(spec, target)

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_update: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.child_parent_match_attr is not None:
            attr = spec.child_parent_match_attr
            if getattr(target, attr) != getattr(parent, attr):
                raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        else:
            parent_fk_attr = spec.parent_fk_attr or f"{spec.parent.name}_id"
            if getattr(target, parent_fk_attr) != parent_id:
                raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"update this {spec.name}")
    else:
        if spec.write_authz is not None:
            spec.write_authz(target, requesting_user, action=f"update this {spec.name}")

    if payload_authz is not None:
        await payload_authz(
            payload=payload,
            requesting_user=requesting_user,
            **(payload_authz_kwargs or {}),
        )

    if spec.discriminator is not None:
        payload_kind = payload.kind
        target_kind = getattr(target, spec.discriminator.column)
        if payload_kind != target_kind:
            raise BadRequestError(
                detail=(
                    f"payload kind {payload_kind!r} does not match {spec.name} "
                    f"kind {target_kind!r}; kind cannot be changed via PATCH"
                )
            )
        kind_spec = spec.discriminator[target_kind]
        detail = getattr(target, kind_spec.detail_relationship)
        # ``model_dump(exclude_unset=True)`` picks up only the fields
        # the client touched and — via the schema's flatten-on-dump
        # ``model_serializer`` (post-#451) — re-projects any nested
        # value-object fields (e.g. ``location: LocationPartial``)
        # back to the flat column names ``detail_fields`` enumerates.
        # Restrict to ``detail_fields`` so the discriminator (``kind``)
        # and any other top-level keys never reach ``repo.patch``.
        dump = payload.model_dump(exclude_unset=True)
        update_fields = {f: dump[f] for f in kind_spec.detail_fields if f in dump}
        async with mutate(
            repo,
            audit_repo,
            actor=requesting_user,
            target=target,
            resource=spec.audit,
            verb="update",
        ):
            await repo.patch(detail, **update_fields)
        return target

    update_fields = payload.model_dump(exclude_unset=True)
    # Compute which columns actually change *before* the patch so an
    # `after_update` hook can react to real value changes (e.g. re-run
    # verification only when `npi` differs), not merely to a field being
    # present in the payload.
    changed_fields = {
        f for f, v in update_fields.items() if getattr(target, f, None) != v
    }
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=target,
        resource=spec.audit,
        verb="update",
    ):
        await repo.patch(target, **update_fields)
        if after_update is not None:
            await after_update(
                row=target,
                payload=payload,
                requesting_user=requesting_user,
                changed_fields=changed_fields,
                **(after_update_kwargs or {}),
            )
    return target


def make_update_handler(
    spec: EntitySpec,
    *,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
    after_update: Callable[..., Awaitable[None]] | None = None,
    after_update_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.mounts._factory import (
        _UPDATE_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(
        spec,
        _UPDATE_SHAPE,
        handle_update,
        payload_authz=payload_authz,
        payload_authz_repos=payload_authz_repos,
        after_update=after_update,
        after_update_repos=after_update_repos,
    )
