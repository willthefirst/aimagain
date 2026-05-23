"""`mount_edge_routes` — the three self-only routes for an M:N edge entity."""

import inspect
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Depends, Request, status

from src.framework.http.responses import (
    APIResponse,
    created_response,
    deleted_response,
    updated_response,
)


def mount_edge_routes(
    router: Any,
    entity: Any,  # `EntitySpec` for an M:N edge with `relation` set
    *,
    list_handler: Callable[..., Awaitable[dict]],
    add_handler: Callable[..., Awaitable[Any]],
    remove_handler: Callable[..., Awaitable[None]],
) -> None:
    """Mount the three self-only routes for an M:N edge entity.

    Routes:
      - ``GET ""`` → renders ``entity.templates.list`` with the
        context returned by ``list_handler``.
      - ``POST /{<to_attr>}`` → calls ``add_handler`` and returns
        ``201 Created`` (new edge: `Location` + `HX-Redirect` to the
        target's detail page) or ``200 OK`` (idempotent re-add:
        `HX-Refresh: true`). Existence check runs in the helper so
        the wire-shape semantics live in one place.
      - ``DELETE /{<to_attr>}`` → calls ``remove_handler`` and
        returns ``204 No Content`` + `HX-Redirect`. Idempotent —
        the handler is expected to no-op if the edge doesn't exist.

    Reads from the spec:
      - ``entity.relation.to_attr`` — path-param name (e.g.
        ``"provider_id"``).
      - ``entity.relation.to_entity.url_collection`` — used for the
        HX-Redirect target (``"/{to_collection}/{id}"``).
      - ``entity.relation.to_entity.repo_dep`` — Depends for the
        opposite-end repo (e.g. the provider repo on a favorite).
      - ``entity.repo_dep`` — Depends for the edge repo.
      - ``entity.read_user_dep`` — auth dep for the requesting actor.
      - ``entity.templates.list`` — Jinja path for the list page.

    The actor's id is sourced from ``entity.read_user_dep``, not from
    the URL — these routes are self-only (the codebase has no
    parametric ``/users/{user_id}/<collection>/...`` form for edges
    today; admin views of others' edges are not exposed in v1).
    """
    if entity.relation is None:
        raise ValueError(
            f"mount_edge_routes({entity.name!r}): entity has no `relation`; "
            "edge mounts require an M2NRelation declaration on the spec."
        )
    if entity.templates.list is None:
        raise ValueError(
            f"mount_edge_routes({entity.name!r}): entity.templates.list is "
            "required for the list endpoint."
        )
    to_attr = entity.relation.to_attr
    to_entity = entity.relation.to_entity
    to_collection = to_entity.url_collection
    # Handler kwarg name for the opposite-end repo follows the spec
    # name convention: `provider_repo` for the provider entity, etc.
    to_repo_kwarg = f"{to_entity.name}_repo"
    list_template = entity.templates.list
    user_dep = entity.read_user_dep
    repo_dep = entity.repo_dep
    to_repo_dep = to_entity.repo_dep

    # Audit repo isn't on the spec — it's the universal audit-log dep
    # every mutation handler takes. Imported lazily to avoid a cycle
    # with repositories.dependencies (which imports from this module's
    # cluster mate `entity_spec`).
    from src.framework.persistence.dependencies import get_audit_repository

    @router.get("", name=f"{entity.name}:list")
    async def _list_route(  # noqa: F811 — closure, not re-exported
        request: Request,
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
    ):
        context = await list_handler(request=request, repo=repo, requesting_user=user)
        return APIResponse.html_response(
            template_name=list_template,
            context=context,
            request=request,
            current_user=user,
        )

    add_route_path = f"/{{{to_attr}}}"

    @router.post(
        add_route_path,
        status_code=status.HTTP_201_CREATED,
        name=f"{entity.name}:add",
    )
    async def _add_route(
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
        to_repo: Any = Depends(to_repo_dep),
        audit_repo: Any = Depends(get_audit_repository),
        **path_kwargs: UUID,
    ):
        target_id = path_kwargs[to_attr]
        # Existence-check before delegating so the wire shape can
        # distinguish first-add (201) from idempotent re-add (200 +
        # HX-Refresh). The handler also no-ops on duplicates, so this
        # second query is the cheapest path to keep the wire contract.
        existing = await repo.get_by_pair(user_id=user.id, **{to_attr: target_id})
        edge = await add_handler(
            **{
                to_attr: target_id,
                "repo": repo,
                to_repo_kwarg: to_repo,
                "audit_repo": audit_repo,
                "requesting_user": user,
            }
        )
        redirect = f"/{to_collection}/{target_id}"
        if existing is not None:
            return updated_response(body={"id": str(edge.id)}, hx_refresh=True)
        return created_response(id=edge.id, location=redirect, hx_redirect=redirect)

    # FastAPI's path-param introspection runs against the declared
    # function signature. `**path_kwargs` doesn't expose `provider_id`
    # to FastAPI — fix by attaching an `inspect.Signature` that names
    # the to_attr explicitly. Same trick `_synthesize_route_fn` uses.
    _add_route.__signature__ = _edge_route_signature(  # type: ignore[attr-defined]
        _add_route, to_attr=to_attr
    )

    @router.delete(
        add_route_path,
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{entity.name}:remove",
    )
    async def _remove_route(
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
        audit_repo: Any = Depends(get_audit_repository),
        **path_kwargs: UUID,
    ):
        target_id = path_kwargs[to_attr]
        await remove_handler(
            **{to_attr: target_id},
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )
        return deleted_response(hx_redirect=f"/{to_collection}/{target_id}")

    _remove_route.__signature__ = _edge_route_signature(  # type: ignore[attr-defined]
        _remove_route, to_attr=to_attr
    )


def _edge_route_signature(fn: Callable, *, to_attr: str) -> inspect.Signature:
    """Rewrite `fn`'s signature so its `**path_kwargs` becomes an
    explicit typed `to_attr: UUID` parameter that FastAPI binds from
    the URL. The wrapper still receives the value via `**path_kwargs`
    in its body — only the FastAPI-visible signature changes."""
    orig = inspect.signature(fn)
    params: list[inspect.Parameter] = [
        inspect.Parameter(
            to_attr, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=UUID
        )
    ]
    for p in orig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        params.append(p)
    return inspect.Signature(parameters=params)
