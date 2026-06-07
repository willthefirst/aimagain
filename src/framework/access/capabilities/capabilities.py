"""Framework-layer capability tree primitives.

`Condition`, `Bundle`, `Gate`, and `CapabilityCheck` are pure tree
structures with no domain knowledge. Domain code builds trees using
these types; the framework provides them as primitives and wires the
standard access routes via `mount_capability_routes`.

No domain imports are allowed here. The domain fills in predicate
functions and template names; the framework owns only the tree
evaluation logic and the route-mount plumbing.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth_config import current_active_user
from src.framework.http.responses import APIResponse


@dataclass(frozen=True)
class Condition:
    """Atomic boolean leaf in a capability tree."""

    label_active: str  # imperative: "Verify email"
    label_done: str  # passive-past: "Email verified"
    met: bool
    fix_url: str  # the resource that changes this condition


@dataclass(frozen=True)
class Bundle:
    """AND node — all children must pass."""

    label_active: str
    label_done: str
    children: tuple  # tuple[Condition | Bundle | Gate, ...]

    @property
    def op(self) -> str:
        return "all"

    @property
    def met(self) -> bool:
        return all(c.met for c in self.children)


@dataclass(frozen=True)
class Gate:
    """OR node — any one child suffices."""

    label_active: str
    label_done: str
    children: tuple  # tuple[Condition | Bundle | Gate, ...]

    @property
    def op(self) -> str:
        return "any"

    @property
    def met(self) -> bool:
        return any(c.met for c in self.children)


@dataclass(frozen=True)
class CapabilityCheck:
    """Evaluated capability tree for a specific user.

    When `bypass` is True (set by the framework for superusers), `granted`
    returns True regardless of the tree's met state. The tree itself is
    preserved so templates can still show the real requirement state.
    """

    name: str
    tree: Any  # Condition | Bundle | Gate
    description: str | None = None
    bypass: bool = False

    @property
    def granted(self) -> bool:
        return self.bypass or self.tree.met


def mount_capability_routes(
    router: APIRouter,
    checks: dict[str, Callable],
    *,
    index_template: str = "users/access/index.html",
    capabilities_list_template: str = "users/access/capabilities/index.html",
    detail_template: str = "users/access/capabilities/detail.html",
) -> None:
    """Mount the three read-only capability routes onto `router`.

    Routes:
      - ``GET ""``                          renders ``index_template`` with
        a ``capabilities_url`` context key pointing at the list page.
      - ``GET /capabilities``               renders ``capabilities_list_template``
        with ``checks`` (all named capabilities, granted/denied),
        ``capability_base_url``, and ``access_index_url``.
      - ``GET /capabilities/{name}``        renders ``detail_template``
        with the evaluated ``CapabilityCheck`` for the named capability;
        returns 404 for unknown names.

    ``checks`` is a ``dict[str, Callable]`` mapping capability name to a
    single-arg predicate ``(user) -> CapabilityCheck``. The framework
    calls each predicate with the current active user and passes the
    result to the template; it never inspects the returned tree itself.

    Template context keys:
      - index: ``capabilities_url``
      - list: ``checks`` (dict[str, CapabilityCheck]), ``capability_base_url``, ``access_index_url``
      - detail: ``check`` (CapabilityCheck), ``access_index_url``, ``capabilities_url``
    """
    _access_index_url = str(router.prefix)
    _capability_base_url = f"{router.prefix}/capabilities"

    @router.get("")
    async def _access_index(
        request: Request,
        user: Any = Depends(current_active_user),
    ):
        return APIResponse.html_response(
            template_name=index_template,
            context={
                "capabilities_url": _capability_base_url,
            },
            request=request,
            current_user=user,
        )

    @router.get("/capabilities")
    async def _capabilities_index(
        request: Request,
        user: Any = Depends(current_active_user),
    ):
        evaluated = {name: fn(user) for name, fn in checks.items()}
        if user.is_superuser:
            evaluated = {
                name: dataclasses.replace(check, bypass=True)
                for name, check in evaluated.items()
            }
        return APIResponse.html_response(
            template_name=capabilities_list_template,
            context={
                "checks": evaluated,
                "capability_base_url": _capability_base_url,
                "access_index_url": _access_index_url,
            },
            request=request,
            current_user=user,
        )

    @router.get("/capabilities/{name}")
    async def _capability_detail(
        name: str,
        request: Request,
        user: Any = Depends(current_active_user),
    ):
        fn = checks.get(name)
        if fn is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        check = fn(user)
        if user.is_superuser:
            check = dataclasses.replace(check, bypass=True)
        return APIResponse.html_response(
            template_name=detail_template,
            context={
                "check": check,
                "access_index_url": _access_index_url,
                "capabilities_url": _capability_base_url,
            },
            request=request,
            current_user=user,
        )
