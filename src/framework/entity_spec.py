"""`EntitySpec`: single declaration of a domain entity.

Phase 1 of the migration described in #317. The migration is
incremental — A1 (#317) introduced the abstraction against `users`,
A2 (#320) extended it to the providers vertical (Provider + three
owned subentities), and later A-series PRs will add the remaining
clusters.

`EntitySpec` is the single source of truth that layer-level sites
read **from** for migrated entities. The mount helpers still consume
`ResourceSpec`; an entity spec derives one via
:meth:`EntitySpec.to_resource_spec`. Phase 2 (a later track) will
introduce generation that binds directly against `EntitySpec`;
phase 1 just makes the declarations load-bearing without changing any
behavior.

The dataclass intentionally stops short of carrying handler
references on its state-axis / subresource descriptors: the spec
sits in `src/specs/` and pulling handlers in would mean
`specs` importing `src.logic.<entity>`, which is the
opposite of the usual layer direction and creates an import cycle
with handlers that read from the spec. Phase 1 keeps the spec as
*metadata*; route files supply the handler in the matching
`mount_*` call. Phase 2 can revisit once the cycle is broken
structurally.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, TypeAdapter

from src.auth_config import current_active_user, current_admin_user
from src.framework.audit import (
    AuditAction,
    AuditedResource,
    make_audited_resource,
    make_snapshotter,
)
from src.framework.authz import assert_owner_or_admin, is_owner_or_admin
from src.framework.polymorphic import DiscriminatorRegistry
from src.framework.resource_routes import QueryParam, ResourceSpec


@dataclass(frozen=True, slots=True)
class AuthDeps:
    """Paired FastAPI auth dependencies for read vs. write routes.

    Every CRUD-shaped entity in the codebase picks from a small set of
    auth-dep patterns:

      - ``AUTHENTICATED`` — both reads and writes require any active
        user (provider, post, the three provider credentials, favorites).
      - ``ADMIN_FOR_WRITE`` — reads allow any active user, writes
        require admin (users).

    Hand-wired ``read_user_dep`` / ``write_user_dep`` still works for
    one-off cases (none today). Mutually exclusive with ``AuthDeps``.

    Mirrors the ``AuthzPolicy`` / ``OWNER_OR_ADMIN`` pattern that
    collapsed the per-target authz pair onto one sentinel.
    """

    read: Callable[..., Any] | None
    write: Callable[..., Any] | None


@dataclass(frozen=True, slots=True)
class AuthzPolicy:
    """Paired raising + predicate forms of a single authorization rule.

    Every entity that mutates by per-target rule (rather than a flat
    route-level admin dep) needs both the raising form (`write_authz`,
    consumed by mutation handlers) and the predicate form (`can_write`,
    bound to detail-handler `can_edit` flags). The two always encode the
    same rule, but historically each spec wired them independently and a
    spec-correctness test pinned the pair on each entity.

    `AuthzPolicy` carries the pair as one declaration. Specs set
    `auth_policy=OWNER_OR_ADMIN` and `EntitySpec.__post_init__` expands
    it to populate `write_authz` + `can_write` with the matched
    callables.
    """

    write_authz: Callable[..., None]
    can_write: Callable[..., bool]


@dataclass(frozen=True, slots=True)
class RouteSet:
    """Per-entity opt-in flags for which `mount_*` calls a route file makes.

    Phase 1 reads these for documentation / test purposes only —
    route files still call the mounts explicitly. Phase 2 will use
    them to drive auto-mounting.

    `form_new` and `form_edit` are separate because providers (the
    first migrated entity that uses forms) mounts two `mount_form`
    calls — one for the create form (no entity id), one for the edit
    form (`on_existing=True`). A single `form` flag couldn't
    distinguish.
    """

    list: bool = False
    detail: bool = False
    delete: bool = False
    create: bool = False
    update: bool = False
    form_new: bool = False
    form_edit: bool = False


@dataclass(frozen=True, slots=True)
class StateAxis:
    """One state-axis subresource on an entity (e.g. `activation` on `user`).

    `handler_path` is the dotted import path of the handler the route
    layer should bind to this axis (e.g.
    ``"src.domain.users.handlers.handle_set_user_activation"``).
    `mount_entity` resolves it via `importlib.import_module` + `getattr`
    at mount time, which is *after* both the spec module and the logic
    module have been imported — so the spec module never imports from
    `src.logic`, preserving the layer direction.

    Carrying it as a string (not a callable) sidesteps the import
    cycle that previously forced the route file to pass the handler
    via `handlers={"activation": ...}`. Specs that pre-date this knob
    can leave it unset and pass the handler explicitly; the explicit
    handler wins.

    `audit_snapshot` is the Pydantic class used to project a row into
    the audit log's `before`/`after` JSON for this axis. The spec's
    `__post_init__` builds the snapshotter once via
    :func:`src.framework.audit.make_snapshotter` and stores it on
    ``audit_snapshot_fn`` so the handler reads
    ``axis.audit_snapshot_fn(target)`` instead of building its own
    module-level snapshotter. Matches the CRUD-side
    ``audit_snapshot → audit`` flow on ``EntitySpec`` — state axes are
    now declaratively complete (body shape + audit action + audit
    snapshot all live on the axis).
    """

    name: str
    body_schema: type[BaseModel]
    action: AuditAction
    handler_path: str | None = None
    response_to_dict: Callable[[Any], dict] | None = None
    audit_snapshot: type[BaseModel] | None = None
    # Derived: populated by `EntitySpec.__post_init__` via
    # `object.__setattr__` after wrapping `audit_snapshot` in
    # `make_snapshotter`. Handlers consume this directly to capture
    # before/after JSON for the audit row.
    audit_snapshot_fn: Callable[[Any], dict[str, Any]] | None = None
    # When True, the framework rejects the request with 403 if the
    # URL's target id equals the requesting user's id — preventing an
    # admin from mutating their own state via this axis. Meaningful
    # for user-shaped entities where the row IS the user; for owned
    # resources the comparison never matches so the flag is a no-op.
    # Wrapping happens in `mount_entity` before the handler is passed
    # to `mount_state_axis`, so the per-entity handler stays free of
    # the boilerplate.
    forbid_self: bool = False


@dataclass(frozen=True, slots=True)
class Templates:
    """Static Jinja paths for the entity's views.

    `form_new` and `form_edit` correspond to the two `mount_form`
    variants (create form / edit form). Posts uses neither (handler
    returns `template_name` in context for per-kind dispatch);
    providers uses both.

    Per-field `None` means "default by convention" — `EntitySpec.__post_init__`
    fills it with ``f"{url_collection}/{verb}.html"`` for any verb the
    entity opts into via `RouteSet`. Specs only declare a field when the
    path diverges from the convention (no current entity does).
    """

    list: str | None = None
    detail: str | None = None
    form_new: str | None = None
    form_edit: str | None = None


@dataclass(frozen=True, slots=True)
class EdgeAudit:
    """Audit binding for entities with non-CRUD verbs.

    `AuditedResource` assumes a `(create, update, delete)` triple,
    which fits CRUD-shaped resources. Edge entities (M:N joins like
    `UserFavorite`) typically have `(add, remove)` verbs and immutable
    edges — no update verb exists. `EdgeAudit` declares the persisted
    `resource_type` string, the snapshot callable, and a verb→action
    map; handlers read both fields and call ``record_audit()`` directly.

    Mutually exclusive with `EntitySpec.audit` — an entity is either
    CRUD-shaped or edge-shaped, not both. Construction-time validation
    enforces it.
    """

    resource_type: str
    snapshot: Callable[[Any], dict]
    actions: dict[str, AuditAction]

    def action_for(self, verb: str) -> AuditAction:
        return self.actions[verb]


@dataclass(frozen=True, slots=True)
class M2NRelation:
    """Declarative many-to-many relationship.

    The two endpoints are `EntitySpec` references; the join table
    stores the edges. Phase 1 captures the shape so the spec is the
    canonical declaration of "this entity is the M:N edge between
    X and Y." Phase 2 framework code can read this to auto-mount
    add/remove edges and the related-list query.
    """

    from_entity: "EntitySpec"
    to_entity: "EntitySpec"
    join_table: str
    from_attr: str
    to_attr: str


@dataclass(frozen=True, slots=True)
class RelatedListSubresource:
    """A `GET /<entity>/{id}/<child.collection>` related-list subresource.

    `child_spec` is a `ResourceSpec` (not `EntitySpec`) so a parent
    can reference unmigrated children — the value can come from
    either a hand-rolled inline `ResourceSpec(...)` or from
    ``<CHILD_ENTITY>.to_resource_spec()`` once the child is migrated.

    `handler_path` is the dotted import path of the handler bound to
    this related-list (same shape as `StateAxis.handler_path`).
    `mount_entity` resolves it via `importlib.import_module` +
    `getattr` at mount time — strings preserve the layer direction
    (`specs` never imports `logic`). Specs that don't set it can pass
    the handler explicitly via `mount_entity(..., handlers={...})`.
    """

    child_spec: ResourceSpec
    template: str
    handler_path: str | None = None
    singleton_alias: tuple[str, Callable[..., Any]] | None = None


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """Declarative identity of a domain entity.

    Read by:
      - Logic-layer handlers, for audit bindings and visibility rules
        (`USER_ENTITY.audit`, `USER_ENTITY.private_fields`,
        `USER_ENTITY.private_field_predicate`).
      - Route files, via :meth:`to_resource_spec` for the `mount_*`
        helpers, plus direct lookup for state-axis / subresource
        shape and list-filter declarations.
      - Spec-correctness tests
        (`src/specs/test_<entity>.py`) that assert the
        spec declares the right things.

    Construction validates pairings that would otherwise leak
    silently — for instance, `private_fields` without a predicate
    would silently leak the fields, `routes.create=True` without a
    `create_adapter` would crash at first request rather than at
    startup. Failing at import time is loud and immediate.

    Owned subentities (sub-resources whose URL nests under a parent —
    `/providers/{provider_id}/licensures/...`) set ``parent`` to
    their parent's `EntitySpec`. :meth:`to_resource_spec` walks the
    chain so the derived `ResourceSpec` carries
    ``parent=parent_entity.to_resource_spec()`` — the mount layer's
    parent-chain machinery handles path building from there.
    """

    # Identity ------------------------------------------------------------
    name: str
    url_collection: str
    id_param: str

    # Model + ownership --------------------------------------------------
    model: type
    owner_attr: str | None = "owner_id"

    # Parent (owned subentity link) --------------------------------------
    parent: "EntitySpec | None" = None

    # FastAPI deps -------------------------------------------------------
    repo_dep: Callable[..., Any] | None = None
    read_user_dep: Callable[..., Any] | None = None
    write_user_dep: Callable[..., Any] | None = None
    write_authz: Callable[..., None] | None = None
    # Predicate form of `write_authz` — non-raising boolean returning
    # True iff the user is allowed to mutate the target. Bound directly
    # to detail-handler context flags (`can_edit = entity.can_write(
    # target, user)`) so handlers don't re-derive the composition.
    # Convention: where `write_authz` is set, `can_write` carries the
    # same rule (e.g. both are `assert_owner_or_admin` / `is_owner_or_admin`
    # for owner-or-admin entities).
    #
    # Prefer `auth_policy=<AuthzPolicy>` over hand-wiring the two — the
    # constructor expands the policy to populate both fields with the
    # matched callables. Mutually exclusive with the hand-wired form.
    can_write: Callable[..., bool] | None = None
    auth_policy: "AuthzPolicy | None" = None
    # `auth_deps` is the declarative pair for `read_user_dep` /
    # `write_user_dep` (FastAPI auth deps used at the *route* level —
    # distinct from `auth_policy` which is the per-target check inside
    # the handler). Mutually exclusive with hand-wired
    # `read_user_dep`/`write_user_dep`.
    auth_deps: "AuthDeps | None" = None

    # Audit --------------------------------------------------------------
    # `audit` and `edge_audit` are mutually exclusive — CRUD-shaped
    # entities use `AuditedResource`; edge entities (M:N joins) use
    # `EdgeAudit`. Construction-time validation enforces it.
    #
    # For CRUD entities, prefer `audit_snapshot=<Schema>` (+ optional
    # `audit_action_stem=...`) over a hand-built `audit=...` — the
    # constructor calls `make_audited_resource(name, audit_snapshot,
    # action_stem=audit_action_stem)` once at import time and stores the
    # result on `audit`. The two forms are mutually exclusive: declare
    # `audit_snapshot` xor `audit`.
    audit: AuditedResource | None = None
    audit_snapshot: type[BaseModel] | Callable[[Any], dict] | None = None
    audit_action_stem: str | None = None
    edge_audit: EdgeAudit | None = None

    # M:N relationships --------------------------------------------------
    relation: M2NRelation | None = None

    # Body adapters + projection ----------------------------------------
    # Accept either a plain Pydantic class or a pre-built `TypeAdapter`.
    # Specs over a single class pass the class directly (the constructor
    # wraps it in `TypeAdapter(...)` once); specs over a discriminated
    # union pass the prebuilt adapter (posts). Mounts that consume these
    # always see a `TypeAdapter` after construction.
    create_adapter: type[BaseModel] | TypeAdapter | None = None
    update_adapter: type[BaseModel] | TypeAdapter | None = None
    # The original Pydantic class when `create_adapter` / `update_adapter`
    # was passed as a class (set by `__post_init__` before wrapping in
    # `TypeAdapter`); `None` when the adapter arrived pre-built (posts'
    # discriminated union). Form-render handlers read this so templates
    # using `field_for(schema, ...)` see a class with `model_fields`.
    create_adapter_class: type[BaseModel] | None = None
    update_adapter_class: type[BaseModel] | None = None
    # Prefer `read_schema=<BaseModel | TypeAdapter>` over a hand-built
    # `read_to_dict=...` — the constructor synthesizes the projection
    # callable. Mutually exclusive.
    read_to_dict: Callable[[Any], dict] | None = None
    read_schema: type[BaseModel] | TypeAdapter | None = None

    # Visibility ---------------------------------------------------------
    private_fields: tuple[str, ...] = ()
    private_field_predicate: Callable[..., bool] | None = None
    # When set, `handle_detail` auto-binds `target_<name>` in the template
    # context to a `project_view` dict using these as the public fields
    # and the spec's `private_fields` / `private_field_predicate` for
    # gating. The split between `public_fields` (per-view shape) and
    # `private_fields` (gated-by-predicate) mirrors `project_view`'s own
    # signature: spec declares *what is private*; `public_fields` declares
    # *which view this is*. Requires `private_field_predicate` to be set.
    public_fields: tuple[str, ...] = ()

    # Route opt-ins ------------------------------------------------------
    routes: RouteSet = field(default_factory=RouteSet)

    # List-page viewer filtering ----------------------------------------
    # When True, `handle_list` passes `exclude_self=requesting_user` to
    # the entity's `list_<collection>` repo method, dropping the viewer
    # from the result set. Anonymous viewers see the full list. Only
    # meaningful for entities whose rows are users (currently just
    # `user`); the kwarg name `exclude_self` is the convention every
    # opt-in repo must accept.
    list_exclude_self: bool = False

    # List default ordering --------------------------------------------
    # SQLAlchemy column expression (e.g. `User.username` or
    # `Post.created_at.desc()`) consumed by `BaseRepository.list_default`
    # — the framework's fallback when an entity has no bespoke
    # `list_<collection>` repo method. Required when `routes.list=True`
    # AND no custom `list_<collection>` exists on the repo; either
    # provide the ordering here or write the bespoke method. Specs whose
    # repo defines `list_<collection>` (e.g. providers, with its
    # licensure-join filter) leave this `None` and the bespoke method
    # owns ordering inline.
    list_order_by: Any = None

    # Delete-route self guard ------------------------------------------
    # When True, `handle_delete` rejects the request with 403 if the
    # URL's target id equals the requesting user's id — preventing an
    # admin from deleting their own account. Symmetric to
    # `StateAxis.forbid_self`. Meaningful for user-shaped entities; on
    # owned resources the comparison never matches (target.id is a
    # row UUID, not a user id) so the flag is a no-op.
    delete_forbid_self: bool = False

    # List-page filters --------------------------------------------------
    filters: tuple[QueryParam, ...] = ()

    # State axes + subresources -----------------------------------------
    state_axes: tuple[StateAxis, ...] = ()
    subresources: tuple[RelatedListSubresource, ...] = ()

    # HX-Redirect targets ------------------------------------------------
    create_redirect: Callable[..., str] | None = None
    update_redirect: Callable[..., str] | None = None
    delete_redirect: Callable[..., str] | None = None

    # Polymorphism -------------------------------------------------------
    # Bound to a `DiscriminatorRegistry` (`src.framework.polymorphic`) for
    # entities whose detail rows live in per-variant tables keyed on a
    # discriminator column. Phase 1 makes the binding load-bearing: the
    # route file reads `Literal[*entity.discriminator.names]` for the
    # form `?kind=` query param instead of importing the registry's
    # `names` tuple directly. Layers that consume the registry's
    # *contents* (dispatch ladders in logic / schema / repo) keep their
    # direct registry imports — the spec only declares the binding.
    discriminator: DiscriminatorRegistry | None = None

    # Templates ----------------------------------------------------------
    templates: Templates = field(default_factory=Templates)

    # Route-prefix override --------------------------------------------
    # Default route prefix is ``f"/{url_collection}"`` (e.g. ``/users``).
    # Favorites is the only entity whose URL doesn't fit the convention
    # — its routes live under ``/users/me/favorites`` — so it sets this
    # field. Other entities leave it ``None`` and the default applies.
    # Consumed by ``make_entity_router(entity)`` in ``base_router.py``.
    prefix_override: str | None = None

    # Detail singleton alias (e.g. `/users/me`) -------------------------
    # `mount_detail`'s `singleton_alias=` kwarg — additionally mounts
    # `GET /<collection>/<alias>` whose id is sourced from a session
    # dep instead of the URL. Used by users (`/users/me`); other
    # entities leave as None.
    singleton_alias: tuple[str, Callable[..., Any]] | None = None

    # Detail / list extras (per-viewer / per-list customization) --------
    # `detail_extras_path` and `list_extras_path` are dotted import paths
    # (e.g. `"src.domain.users.handlers.user_detail_extras"`) to the
    # per-viewer extras callable consumed by `make_detail_handler` /
    # `make_list_handler`. The path is resolved lazily via
    # `importlib.import_module` + `getattr` at mount time, *after* both
    # the spec module and the logic module have been imported — so the
    # spec module never has to import from `src.logic.<entity>`, which
    # would close the cycle (logic modules import from the spec). Same
    # late-binding trick `StateAxis.handler_path` already uses.
    #
    # `detail_extras_repos` / `list_extras_repos` declare typed repo
    # kwargs the extras callable receives. Repository classes live below
    # specs in the import order, so the type-class import is cycle-safe
    # and the field carries real classes (not strings).
    detail_extras_path: str | None = None
    detail_extras_repos: tuple[tuple[str, type], ...] = ()
    list_extras_path: str | None = None
    list_extras_repos: tuple[tuple[str, type], ...] = ()

    # Static context bindings -------------------------------------------
    # Constant key→value pairs that `handle_detail` / `handle_list` merge
    # into the template context after the framework's auto-injected keys
    # and before the entity's extras callable runs. Use this for values
    # that are computed once at spec-construction time (registry tuples,
    # enum lists, feature flags) — anything dynamic stays on the extras
    # callable. Posts uses this for `post_kinds` so its list page renders
    # per-kind "New X" links without a dedicated extras callable.
    #
    # The dict is shared by reference, so values should be immutable
    # (tuples / frozen lists / plain enums). Spec consumers read from
    # `entity.static_context` but never mutate.
    static_context: dict[str, Any] = field(default_factory=dict)

    # Owned-subentity registry. Populated in __post_init__: when a spec
    # is constructed with `parent=<P>`, the child appends itself to
    # `P._children` (in-place mutation; the frozen dataclass guarantees
    # only forbids field reassignment, not list mutation). Exposed via
    # the `children` property as an immutable tuple.
    _children: list["EntitySpec"] = field(
        default_factory=list, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Mirror `ResourceSpec.__post_init__` — declaring private fields
        # without a predicate would silently leak them.
        if self.private_fields and self.private_field_predicate is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares private_fields="
                f"{self.private_fields!r} but no private_field_predicate — "
                "private fields cannot be gated without a predicate."
            )
        # `public_fields` drives the `target_<name>` projection in
        # `handle_detail`; without a predicate the gating step would
        # silently allow every private field through.
        if self.public_fields and self.private_field_predicate is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares public_fields="
                f"{self.public_fields!r} but no private_field_predicate — "
                "the projection cannot gate private fields without one."
            )
        # `list_exclude_self` is consumed only by `handle_list`; if no
        # list route is opted in, the flag is dead.
        if self.list_exclude_self and not self.routes.list:
            raise ValueError(
                f"EntitySpec({self.name!r}) sets list_exclude_self=True but "
                "routes.list is False — the flag would never apply."
            )
        # `delete_forbid_self` is consumed only by `handle_delete`; if no
        # delete route is opted in, the flag is dead.
        if self.delete_forbid_self and not self.routes.delete:
            raise ValueError(
                f"EntitySpec({self.name!r}) sets delete_forbid_self=True but "
                "routes.delete is False — the flag would never apply."
            )
        # State-axis names must be unique; route mounting iterates by
        # name, so duplicates would shadow each other silently.
        axis_names = [axis.name for axis in self.state_axes]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares duplicate state-axis "
                f"names: {axis_names}"
            )
        # Build the audit snapshotter for each axis that declares an
        # `audit_snapshot` schema. Mirrors the CRUD-side
        # `audit_snapshot → audit` flow above: the schema lives on the
        # declarative pair (axis), the constructor wraps it once via
        # `make_snapshotter`, and handlers read `axis.audit_snapshot_fn`
        # instead of binding their own module-level snapshotter.
        # Declaring `audit_snapshot_fn` directly alongside `audit_snapshot`
        # is ambiguous — pick one.
        for axis in self.state_axes:
            if axis.audit_snapshot is not None and axis.audit_snapshot_fn is not None:
                raise ValueError(
                    f"EntitySpec({self.name!r}) state-axis {axis.name!r} "
                    "declares both `audit_snapshot` and `audit_snapshot_fn`; "
                    "they are mutually exclusive — pass the schema via "
                    "`audit_snapshot` and let the spec build the callable."
                )
            if axis.audit_snapshot is not None:
                object.__setattr__(
                    axis,
                    "audit_snapshot_fn",
                    make_snapshotter(axis.audit_snapshot),
                )
        # Wrap a plain Pydantic class in `TypeAdapter(...)` so the
        # downstream mounts (which expect an adapter) get one regardless
        # of which form the spec was constructed with. Discriminated-union
        # adapters (posts) arrive pre-built and pass through unchanged.
        # When a plain class was passed, the original is remembered as
        # `<field>_class` so form templates that introspect `model_fields`
        # (via `field_for(schema, ...)`) can read the unwrapped class.
        for field_name in ("create_adapter", "update_adapter"):
            current = getattr(self, field_name)
            class_attr = f"{field_name}_class"
            if current is None:
                object.__setattr__(self, class_attr, None)
            elif isinstance(current, TypeAdapter):
                object.__setattr__(self, class_attr, None)
            else:
                object.__setattr__(self, class_attr, current)
                object.__setattr__(self, field_name, TypeAdapter(current))
        # `routes.create=True` without a create adapter would crash at
        # first request — `mount_create` already raises here, but
        # surfacing the misconfiguration at spec-construction time is
        # earlier and more localized.
        if self.routes.create and self.create_adapter is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) has routes.create=True but no "
                "create_adapter — mount_create cannot parse a body without one."
            )
        if self.routes.update and self.update_adapter is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) has routes.update=True but no "
                "update_adapter — mount_update cannot parse a body without one."
            )
        # An owned subentity that doesn't expose any HTTP routes is
        # unreachable. Either the routes are wrong or the parent link
        # is — either way, surface the inconsistency at import time.
        if self.parent is not None and not self._has_any_route():
            raise ValueError(
                f"EntitySpec({self.name!r}) declares parent="
                f"{self.parent.name!r} but no routes are opted in — "
                "the subentity would be unreachable."
            )
        # Register this child with its parent's owned-subentity list
        # so `parent.children` reflects the construction order. List
        # mutation on a frozen dataclass is permitted (we never reassign
        # `_children`, just mutate the existing list in place).
        if self.parent is not None:
            self.parent._children.append(self)
        # CRUD-shaped vs edge-shaped audit binding is an either/or
        # choice; declaring both would be ambiguous and almost
        # certainly a misconfiguration.
        if self.audit is not None and self.edge_audit is not None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares both `audit` and "
                "`edge_audit`; they are mutually exclusive — CRUD-shaped "
                "entities use AuditedResource, edge entities use EdgeAudit."
            )
        # `audit_snapshot` is the declarative form: the constructor
        # builds `audit` from name + schema (+ optional action_stem).
        # Declaring both forms is ambiguous; the user picked one and
        # forgot the other, almost certainly.
        # Default `audit_snapshot` from `read_schema` when the read schema
        # is a Pydantic class and no audit binding has been declared. The
        # codebase convention is that audit snapshots are byte-identical
        # to the read projection except for entities that explicitly
        # diverge (posts: discriminated-union flatten; users: omits id).
        # Those entities still set `audit_snapshot=` explicitly.
        # `TypeAdapter` adapters are skipped — posts' read schema is a
        # discriminated-union adapter whose audit snapshot is a distinct
        # callable.
        if (
            self.audit_snapshot is None
            and self.audit is None
            and isinstance(self.read_schema, type)
            and issubclass(self.read_schema, BaseModel)
        ):
            object.__setattr__(self, "audit_snapshot", self.read_schema)
        if self.audit_snapshot is not None and self.audit is not None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares both `audit_snapshot` "
                "and `audit`; they are mutually exclusive — pass the "
                "schema/callable via `audit_snapshot` and let the spec "
                "build the AuditedResource, or build it explicitly via "
                "`audit=`."
            )
        if self.audit_action_stem is not None and self.audit_snapshot is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) sets `audit_action_stem=` "
                f"{self.audit_action_stem!r} but no `audit_snapshot` — "
                "the stem is only consumed when building from a snapshot."
            )
        if self.audit_snapshot is not None:
            built = make_audited_resource(
                self.name,
                self.audit_snapshot,
                action_stem=self.audit_action_stem,
            )
            object.__setattr__(self, "audit", built)
        # `read_schema` is the declarative form of `read_to_dict`: the
        # constructor synthesizes a callable that validates an ORM row
        # through the schema/adapter and dumps it to a JSON-mode dict.
        # The two forms are mutually exclusive; declaring both means the
        # caller forgot to drop one.
        if self.read_schema is not None and self.read_to_dict is not None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares both `read_schema` and "
                "`read_to_dict`; they are mutually exclusive — pass the "
                "schema/adapter via `read_schema` and let the spec build "
                "the projection callable."
            )
        # `auth_policy` is the declarative pair. Both raw fields stay
        # supported for the rare entity whose write_authz + can_write
        # don't share a sentinel (none today). Declaring both forms is
        # ambiguous — the caller almost certainly forgot to drop one.
        if self.auth_policy is not None and (
            self.write_authz is not None or self.can_write is not None
        ):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares `auth_policy` plus "
                "an explicit `write_authz` / `can_write`; they are "
                "mutually exclusive — pass the pair via `auth_policy` or "
                "set the two callables explicitly."
            )
        if self.auth_policy is not None:
            object.__setattr__(self, "write_authz", self.auth_policy.write_authz)
            object.__setattr__(self, "can_write", self.auth_policy.can_write)
        # `auth_deps` mirrors `auth_policy`: the constructor expands the
        # paired declaration into the two slot fields. Mutually exclusive
        # with hand-wired `read_user_dep` / `write_user_dep`.
        if self.auth_deps is not None and (
            self.read_user_dep is not None or self.write_user_dep is not None
        ):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares `auth_deps` plus "
                "an explicit `read_user_dep` / `write_user_dep`; they "
                "are mutually exclusive — pass the pair via `auth_deps` "
                "or set the two deps explicitly."
            )
        if self.auth_deps is not None:
            object.__setattr__(self, "read_user_dep", self.auth_deps.read)
            object.__setattr__(self, "write_user_dep", self.auth_deps.write)
        # Validate extras bindings: a path requires an opted-in route
        # (otherwise the extras would never run); typed-repo kwargs
        # require a callable consumer (otherwise the kwargs are dead).
        # Validation lives here (not in `mount_entity`) so the
        # misconfiguration surfaces at spec-construction time.
        if self.detail_extras_path is not None and not self.routes.detail:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares detail_extras_path but "
                "routes.detail is False — the extras would never run."
            )
        if self.detail_extras_repos and self.detail_extras_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares detail_extras_repos but "
                "no detail_extras_path — the typed-repo kwargs would have "
                "no consumer."
            )
        if self.list_extras_path is not None and not self.routes.list:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares list_extras_path but "
                "routes.list is False — the extras would never run."
            )
        if self.list_extras_repos and self.list_extras_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares list_extras_repos but "
                "no list_extras_path — the typed-repo kwargs would have "
                "no consumer."
            )
        if self.read_schema is not None:
            schema = self.read_schema
            if isinstance(schema, TypeAdapter):

                def _projection(obj: Any, _adapter: TypeAdapter = schema) -> dict:
                    return _adapter.validate_python(obj).model_dump(mode="json")

            else:

                def _projection(obj: Any, _cls: type[BaseModel] = schema) -> dict:
                    return _cls.model_validate(obj).model_dump(mode="json")

            object.__setattr__(self, "read_to_dict", _projection)
        # Default templates by convention: any opted-in verb whose
        # `templates.<verb>` field is None gets `<url_collection>/<verb>.html`.
        # Specs only declare a path when it diverges from this default.
        # Non-opted-in verbs stay `None` so `test_user_favorite` (which
        # asserts `detail is None` for the edge entity) still holds.
        resolved = {
            "list": self.templates.list,
            "detail": self.templates.detail,
            "form_new": self.templates.form_new,
            "form_edit": self.templates.form_edit,
        }
        for verb in resolved:
            if resolved[verb] is None and getattr(self.routes, verb, False):
                resolved[verb] = f"{self.url_collection}/{verb}.html"
        if any(resolved[v] != getattr(self.templates, v) for v in resolved):
            object.__setattr__(self, "templates", Templates(**resolved))

    def _has_any_route(self) -> bool:
        r = self.routes
        return (
            r.list
            or r.detail
            or r.create
            or r.update
            or r.delete
            or r.form_new
            or r.form_edit
        )

    @property
    def children(self) -> tuple["EntitySpec", ...]:
        """Owned-subentity specs whose ``parent`` is this entity.

        Populated automatically as children declare ``parent=self``;
        order matches the children's construction order. Returned as a
        tuple so callers cannot mutate the underlying registry.

        Consumers: the generic ``handle_create`` walks
        ``spec.children`` so the standard top-level create path appends
        inline-child rows automatically (providers' credential lists).
        Adding a fourth credential is a one-file change (the new spec)
        with no edit to the create handler.
        """
        return tuple(self._children)

    def to_resource_spec(self) -> ResourceSpec:
        """Derive a `ResourceSpec` for the mount helpers.

        Phase 1 keeps `ResourceSpec` as the layer-of-glue that the
        existing `mount_*` functions consume. Route files do
        ``<ENTITY>_SPEC = <ENTITY>_ENTITY.to_resource_spec()`` and
        pass that to the mount calls — same call shapes, just the
        source of truth moves up one level.

        Owned-subentity specs (`self.parent is not None`) carry a
        derived `parent` `ResourceSpec` so the mount layer's
        parent-chain machinery can walk it for path nesting.
        """
        parent_rs = self.parent.to_resource_spec() if self.parent is not None else None
        return ResourceSpec(
            collection=self.url_collection,
            id_param=self.id_param,
            repo_dep=self.repo_dep,
            audit_resource=self.audit,
            read_user_dep=self.read_user_dep,
            write_user_dep=self.write_user_dep,
            write_authz=self.write_authz,
            create_adapter=self.create_adapter,
            update_adapter=self.update_adapter,
            read_to_dict=self.read_to_dict,
            list_template=self.templates.list,
            detail_template=self.templates.detail,
            create_redirect=self.create_redirect,
            update_redirect=self.update_redirect,
            delete_redirect=self.delete_redirect,
            private_fields=self.private_fields,
            private_field_predicate=self.private_field_predicate,
            parent=parent_rs,
        )

    def state_axis(self, name: str) -> StateAxis:
        """Look up a state axis by name.

        Lets handlers read the audit `AuditAction` for a non-CRUD
        axis directly from the spec instead of hardcoding the enum:

            action=USER_ENTITY.state_axis("activation").action
        """
        for axis in self.state_axes:
            if axis.name == name:
                return axis
        raise KeyError(f"EntitySpec({self.name!r}) has no state axis named {name!r}")


# Canonical `AuthzPolicy` sentinel for owner-or-admin entities. Pairs
# the raising form (`assert_owner_or_admin`) with the predicate form
# (`is_owner_or_admin`) defined in `src/framework/authz.py`. Specs that
# follow this rule (provider, post, all three credentials) declare
# `auth_policy=OWNER_OR_ADMIN` and the constructor expands the pair.
#
# The sentinel lives next to `AuthzPolicy` (not in `_authz.py`) because
# `_authz.py` would otherwise import this module — `entity_spec` is
# imported via `resource_routes` → `responses` → `_authz` early in the
# load order, and adding the reverse edge would close the cycle. Keeping
# the import direction `entity_spec → _authz` matches the layer matrix
# (api.common may read from logic primitives) and is import-cycle-safe.
OWNER_OR_ADMIN: AuthzPolicy = AuthzPolicy(
    write_authz=assert_owner_or_admin,
    can_write=is_owner_or_admin,
)


# Canonical `AuthDeps` sentinels for the two route-level auth-dep
# patterns the codebase uses. Specs that follow either pattern declare
# `auth_deps=<sentinel>` and the constructor expands the pair onto
# `read_user_dep` / `write_user_dep`.
AUTHENTICATED: AuthDeps = AuthDeps(
    read=current_active_user,
    write=current_active_user,
)
ADMIN_FOR_WRITE: AuthDeps = AuthDeps(
    read=current_active_user,
    write=current_admin_user,
)


class Redirects:
    """Canned redirect-callable factories for the `*_redirect` spec fields.

    `EntitySpec.create_redirect` / `update_redirect` / `delete_redirect`
    are callables receiving every path param the route binds as kwargs
    (parent ids for sub-resources + the entity's own id after create /
    update). The two shapes that occur in this codebase are:

      - "send the user to the edit form" — providers + credentials all
        redirect to `/providers/{provider_id}/form`.
      - "send the user to the detail page" — posts redirect to
        `/posts/{post_id}` after update.

    Both factories take `collection` + `id_param` strings (so a spec
    can self-reference via literals, sidestepping the closure-over-
    not-yet-built-spec problem) and return a `**kwargs`-accepting
    callable that picks the right kwarg out and formats the URL.
    """

    @staticmethod
    def to_edit_form(collection: str, id_param: str) -> Callable[..., str]:
        """Build a redirect callable producing ``/<collection>/{id}/form``.

        Reads the id from ``kwargs[id_param]``. Used by providers
        (post-create / post-update redirect to their own edit form) and
        by all three credential subentities (which redirect to the
        parent provider's edit form — `id_param` is the parent's).
        """

        def _redirect(**kwargs: Any) -> str:
            return f"/{collection}/{kwargs[id_param]}/form"

        return _redirect

    @staticmethod
    def to_detail(collection: str, id_param: str) -> Callable[..., str]:
        """Build a redirect callable producing ``/<collection>/{id}``.

        Used by posts (post-update redirects to the detail page).
        """

        def _redirect(**kwargs: Any) -> str:
            return f"/{collection}/{kwargs[id_param]}"

        return _redirect
