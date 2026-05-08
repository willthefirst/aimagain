"""Generic CRUD route registration for provider sub-resources.

The provider profile owns three credential sub-resources (licensures,
educations, certifications) whose POST/PATCH/DELETE routes differ only in
the path segment, the schema adapters, the read-dict helper, the logic
handler trio, and the kwarg name used to pass the child id.

`SubresourceSpec` declares those knobs once per sub-resource;
`register_subresource_routes` mounts the three routes on a shared
`APIRouter`. Behavior — paths, request bodies, response status codes,
response bodies, and `Location` / `HX-Redirect` headers — matches the
hand-written equivalents byte-for-byte.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Depends, Request, status
from pydantic import TypeAdapter

from src.api.common.forms import parse_and_validate_form
from src.api.common.responses import (
    created_response,
    deleted_response,
    updated_response,
)


@dataclass(frozen=True)
class SubresourceSpec:
    collection: str
    child_id_param: str
    create_adapter: TypeAdapter
    update_adapter: TypeAdapter
    read_to_dict: Callable[[Any], dict]
    create_handler: Callable[..., Awaitable[Any]]
    update_handler: Callable[..., Awaitable[Any]]
    delete_handler: Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class SubresourceDeps:
    """The three FastAPI dependency callables every sub-resource route uses."""

    repo: Callable[..., Any]
    audit_repo: Callable[..., Any]
    user: Callable[..., Any]


def register_subresource_routes(
    router: Any,
    spec: SubresourceSpec,
    *,
    deps: SubresourceDeps,
) -> None:
    """Mount POST / PATCH / DELETE for `spec.collection` on `router`.

    The mounted handlers route the parsed payload through the spec's
    adapters and forward to the spec's logic handlers using the spec's
    `child_id_param` name (so existing handlers like
    `handle_update_licensure(licensure_id=...)` keep working without
    signature changes).
    """
    collection = spec.collection
    child_param = spec.child_id_param

    @router.post(f"/{{provider_id}}/{collection}", status_code=status.HTTP_201_CREATED)
    async def _create(
        provider_id: UUID,
        request: Request,
        repo=Depends(deps.repo),
        audit_repo=Depends(deps.audit_repo),
        user=Depends(deps.user),
    ):
        payload = await parse_and_validate_form(request, spec.create_adapter)
        created = await spec.create_handler(
            provider_id=provider_id,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )
        return created_response(
            id=created.id,
            location=f"/providers/{provider_id}",
            hx_redirect=f"/providers/{provider_id}/form",
        )

    @router.patch(f"/{{provider_id}}/{collection}/{{child_id}}")
    async def _patch(
        provider_id: UUID,
        child_id: UUID,
        request: Request,
        repo=Depends(deps.repo),
        audit_repo=Depends(deps.audit_repo),
        user=Depends(deps.user),
    ):
        payload = await parse_and_validate_form(request, spec.update_adapter)
        updated = await spec.update_handler(
            provider_id=provider_id,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
            **{child_param: child_id},
        )
        return updated_response(
            body=spec.read_to_dict(updated),
            hx_redirect=f"/providers/{provider_id}/form",
        )

    @router.delete(
        f"/{{provider_id}}/{collection}/{{child_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def _delete(
        provider_id: UUID,
        child_id: UUID,
        repo=Depends(deps.repo),
        audit_repo=Depends(deps.audit_repo),
        user=Depends(deps.user),
    ):
        await spec.delete_handler(
            provider_id=provider_id,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
            **{child_param: child_id},
        )
        return deleted_response(hx_redirect=f"/providers/{provider_id}/form")
