"""Framework-layer capability tree primitives.

Two layers, in order:

1. **Tree value types** — `Condition`, `Bundle`, `Gate`, `CapabilityCheck`.
   Pure data: an evaluated tree for one (actor, capability) pair. Bundles
   are AND, Gates are OR, Conditions are leaves with `met`/`fix_url`.

2. **DAG primitives** — `Leaf`, `LeafRegistry`. A `Leaf` is a named,
   reusable boolean fact about an actor (e.g. `"email_verified"`) that
   knows its display copy and fix URL. `LeafRegistry` is the name → leaf
   map so a capability can compose its tree from named leaves rather
   than inlining `Condition(label="…", fix_url="…", met=…)` blocks per
   capability. The DAG that emerges (capabilities → leaves) is what
   makes "which capabilities depend on leaf X" a one-liner instead of a
   grep.

Domain code:
- Registers each `Leaf` once with its labels, fix URL, and a predicate.
- Builds capability `check_*` functions whose trees compose registered
  leaves via `leaf.evaluate(actor)`, returning the `Condition` value
  type the existing renderer expects.

No domain imports are allowed here. The domain fills in predicate
functions and template names; the framework owns the leaf primitive,
the tree value types, and the route-mount plumbing.
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


@dataclass(frozen=True)
class Leaf:
    """A named boolean fact about an actor, plus its locked-affordance copy.

    A leaf is the smallest unit of a capability tree: it answers one
    yes/no question (`predicate(actor)`) and carries everything a
    `Condition` node needs to render — labels and the fix URL the user
    can click to flip the bit.

    Names are addresses: `Leaf("email_verified", …)` makes the leaf
    discoverable via `LeafRegistry.get("email_verified")` and lets two
    capabilities reference the same fact without re-declaring its
    label/fix-URL.

    Use `leaf.evaluate(actor)` to produce a `Condition` for a tree. The
    predicate is invoked once per evaluation — leaves are not cached,
    because capability checks are read-light and per-request.
    """

    name: str
    label_active: str  # imperative: "Verify your email"
    label_done: str  # passive-past: "Email verified"
    fix_url: str  # deep-link to the resource that flips this bit
    predicate: Callable[[Any], bool]

    def evaluate(self, actor: Any) -> Condition:
        return Condition(
            label_active=self.label_active,
            label_done=self.label_done,
            met=bool(self.predicate(actor)),
            fix_url=self.fix_url,
        )


class LeafRegistry:
    """Name → Leaf map. The DAG's node table.

    Domain code constructs one registry, calls `register(leaf)` per
    fact, and looks leaves up by name from capability `check_*`
    functions. Registration is insert-once: re-registering a name
    raises, so a domain typo can't silently shadow an existing leaf.

    Why a class, not a `dict`: registration is the one operation that
    needs to enforce the insert-once invariant, and `.all()` returning
    a tuple (immutable snapshot) keeps any future
    "introspect-all-leaves" tooling from holding a mutable reference.
    Both are cheap to express on a dict; the class is the place to
    name them.
    """

    def __init__(self) -> None:
        self._leaves: dict[str, Leaf] = {}

    def register(self, leaf: Leaf) -> Leaf:
        """Insert `leaf` under its name. Raises if the name is taken so
        a typo or accidental re-import can't shadow an existing fact."""
        if leaf.name in self._leaves:
            raise ValueError(f"Leaf {leaf.name!r} already registered")
        self._leaves[leaf.name] = leaf
        return leaf

    def get(self, name: str) -> Leaf:
        """Look up by name. Raises KeyError on miss — callers are
        expected to reference known leaves by name literal, so a miss
        is a domain bug, not a runtime branch."""
        return self._leaves[name]

    def all(self) -> tuple[Leaf, ...]:
        """All registered leaves as an immutable snapshot (insertion
        order). Use for introspection — "list every fact this app
        gates on" — without exposing the underlying dict."""
        return tuple(self._leaves.values())


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
