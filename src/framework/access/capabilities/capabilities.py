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

3. **Traversal** — `WizardStep` + `wizard_step(check)`. A pure projection
   of an evaluated tree into "what should the user do next": the first
   unmet requirement, or the open branches of an unmet `Gate` (a choice),
   or done. This is what lets a capability page *guide* (one next action)
   as well as *explain* (the whole requirement tree). It reads the same
   `met`/`fix_url` the renderer uses, so guidance can't disagree with the
   tree.

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

    `granted` is the tree's own met state — there is no out-of-band
    override flag. Administrative overrides (superuser) are modeled
    INSIDE the tree by the domain: the check composes an OR `Gate`
    whose extra child is the override condition, so the detail page
    shows *why* access is granted instead of contradicting an unmet
    tree (see `_superuser_gate` in `src/domain/logic/capabilities.py`).
    """

    name: str
    tree: Any  # Condition | Bundle | Gate
    description: str | None = None

    @property
    def granted(self) -> bool:
        return self.tree.met


@dataclass(frozen=True)
class WizardStep:
    """The user's current position walking a capability tree toward granted.

    Produced by `wizard_step(check)` — a pure projection of an evaluated
    `CapabilityCheck` into "what to do next", rendered as a single
    call-to-action above the full requirement tree.

    `kind`:
      - ``"done"`` — the capability is granted; `options` is empty.
      - ``"condition"`` — one actionable requirement is next; `options`
        holds exactly that `Condition` (its `fix_url` is the CTA).
      - ``"choice"`` — the next unmet requirement is an OR (`Gate`) with
        more than one open branch; `options` holds one representative
        `Condition` per open branch, `options[0]` being the default and
        the rest offered as "or do this instead" switches.
      - ``"blocked"`` — ungranted but nothing open is self-serviceable
        (every unmet leaf lacks a `fix_url`); `options` is empty. Not
        reachable for user-facing capabilities today (the only
        fix-URL-less leaf is `superuser`, whose gate is always met when
        present), but the walker reports it honestly rather than "done".

    `index`/`total` place the step among the root's direct requirements
    ("step 2 of 2") for a progress rail; both are 1 for a single-node or
    root-`Gate` tree.
    """

    kind: str
    options: tuple[Condition, ...]
    index: int
    total: int

    @property
    def primary(self) -> Condition | None:
        """The default action — `options[0]`, or `None` when done/blocked."""
        return self.options[0] if self.options else None

    @property
    def alternatives(self) -> tuple[Condition, ...]:
        """Non-default choice branches (empty unless `kind == "choice"`)."""
        return self.options[1:]

    @property
    def is_choice(self) -> bool:
        return self.kind == "choice"

    @property
    def done(self) -> bool:
        return self.kind == "done"


def _unmet_children(node: Any) -> tuple:
    return tuple(c for c in node.children if not c.met)


def _representative(node: Any) -> Condition | None:
    """The first self-serviceable `Condition` in `node`'s unmet subtree,
    following the default (first-unmet) branch at each level, or `None`
    if the subtree is met or has no leaf carrying a `fix_url`."""
    if node.met:
        return None
    if isinstance(node, Condition):
        return node if node.fix_url else None
    for child in _unmet_children(node):
        rep = _representative(child)
        if rep is not None:
            return rep
    return None


def _actionable(node: Any) -> tuple[Condition, ...]:
    """The actionable option(s) at `node`'s current step: one `Condition`
    for a `Bundle`/`Condition` (its first unmet, self-serviceable
    requirement), or one representative per open branch of an unmet
    `Gate` (the choice). Empty when met or wholly non-actionable."""
    if node.met:
        return ()
    if isinstance(node, Condition):
        return (node,) if node.fix_url else ()
    if isinstance(node, Gate):
        return tuple(rep for c in _unmet_children(node) if (rep := _representative(c)))
    # Bundle (AND): advance into the first unmet child.
    return _actionable(_unmet_children(node)[0])


def _progress(tree: Any) -> tuple[int, int]:
    """Position among the root's direct requirements as `(index, total)`,
    1-based. `total` is the count of top-level requirements (root
    `Bundle` children, else 1); `index` is the first unmet one, clamped
    to `total` once all are met."""
    children = getattr(tree, "children", None)
    if not children or isinstance(tree, Gate):
        return (1, 1)
    total = len(children)
    met = sum(1 for c in children if c.met)
    return (min(met + 1, total), total)


def wizard_step(check: CapabilityCheck) -> WizardStep:
    """Walk an evaluated capability tree to the user's next action.

    Pure projection over `check.tree` — see `WizardStep` for the return
    shape. Superuser overrides need no special-casing: the override is
    modeled in-tree as a met `Gate` branch, so a granted superuser
    reports ``"done"`` like anyone else.
    """
    tree = check.tree
    index, total = _progress(tree)
    if check.granted:
        return WizardStep(kind="done", options=(), index=total, total=total)
    options = _actionable(tree)
    if not options:
        return WizardStep(kind="blocked", options=(), index=index, total=total)
    kind = "choice" if len(options) > 1 else "condition"
    return WizardStep(kind=kind, options=options, index=index, total=total)


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

    `requires` declares this leaf's upstream dependencies in the DAG —
    other leaves that must hold for this one to be meaningful (e.g.
    `OWNS_PROGRAM_LEAF.requires = (ORG_REP_ANY_LEAF,)`: you can't own
    a program without a verified org rep on its org). Composers
    `evaluate_chain(actor)` to splat the dependency closure into a
    parent Bundle's children, instead of every consumer remembering to
    list the prereqs as siblings. The bare `evaluate(actor)` is
    unchanged: it returns just this leaf's own `Condition` — use it
    when you don't want the chain (e.g. one fact's bool for a
    standalone gate).

    The predicate is invoked once per evaluation — leaves are not
    cached, because capability checks are read-light and per-request.
    """

    name: str
    label_active: str  # imperative: "Verify your email"
    label_done: str  # passive-past: "Email verified"
    fix_url: str  # deep-link to the resource that flips this bit
    predicate: Callable[[Any], bool]
    requires: tuple["Leaf", ...] = ()

    def evaluate(self, actor: Any) -> Condition:
        return Condition(
            label_active=self.label_active,
            label_done=self.label_done,
            met=bool(self.predicate(actor)),
            fix_url=self.fix_url,
        )

    def evaluate_chain(self, actor: Any) -> tuple[Condition, ...]:
        """Yield this leaf's `Condition` preceded by every transitive
        prerequisite, in dependency-first order, dedup'd by leaf name.

        Splat the result into a parent `Bundle`'s `children` so the
        prereqs appear as siblings of the leaf — same flat structure
        the existing renderer expects, but declared once on the leaf
        instead of duplicated at every consumer site.
        """
        seen: set[str] = set()
        chain: list[Condition] = []

        def visit(leaf: "Leaf") -> None:
            if leaf.name in seen:
                return
            seen.add(leaf.name)
            for req in leaf.requires:
                visit(req)
            chain.append(leaf.evaluate(actor))

        visit(self)
        return tuple(chain)


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
    single-arg predicate ``(user) -> CapabilityCheck | None``. The
    framework calls each predicate with the current active user and
    passes the result to the template; it never inspects the returned
    tree itself. A predicate may return ``None`` to declare the
    capability *not applicable* to this user — it is omitted from the
    list page and its detail page 404s, exactly like an unknown name.
    The domain uses this for operational capabilities (superuser) that
    should never be advertised to users who don't hold them.

    Template context keys:
      - index: ``capabilities_url``
      - list: ``checks`` (dict[str, CapabilityCheck]), ``capability_base_url``, ``access_index_url``
      - detail: ``check`` (CapabilityCheck), ``step`` (WizardStep — the
        guided next action for `check`), ``access_index_url``, ``capabilities_url``
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
        evaluated = {
            name: check
            for name, fn in checks.items()
            if (check := fn(user)) is not None
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
        if check is None:
            # Not applicable to this user (e.g. the superuser capability
            # for a non-superuser) — indistinguishable from unknown.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return APIResponse.html_response(
            template_name=detail_template,
            context={
                "check": check,
                "step": wizard_step(check),
                "access_index_url": _access_index_url,
                "capabilities_url": _capability_base_url,
            },
            request=request,
            current_user=user,
        )
