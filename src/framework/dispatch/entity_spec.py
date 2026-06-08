"""EntitySpec: the single declaration every framework consumer reads."""

from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import Depends
from pydantic import BaseModel, TypeAdapter

from src.auth_config import current_active_user, current_admin_user
from src.framework.access.authz.authz import assert_owner_or_admin, is_owner_or_admin
from src.framework.audit.core import (
    AuditAction,
    AuditedResource,
    make_audited_resource,
    make_snapshotter,
)
from src.framework.dispatch.filters import Filter
from src.framework.dispatch.resource_routes import QueryParam, ResourceSpec
from src.framework.persistence.polymorphic import DiscriminatorRegistry


@dataclass(frozen=True, slots=True)
class AuthDeps:
    """Paired FastAPI auth dependencies for read vs. write routes."""

    read: Callable[..., Any] | None
    write: Callable[..., Any] | None


@dataclass(frozen=True, slots=True)
class AuthzPolicy:
    """Paired raising + predicate forms of a single authorization rule."""

    write_authz: Callable[..., None]
    can_write: Callable[..., bool]


@dataclass(frozen=True, slots=True)
class ReadPolicy:
    """Capability gate for read access to an entity's data.

    Distinct from `AuthzPolicy` (which gates per-object mutation) because
    read gating is per-user and type-scoped — "can this user see this kind
    of data at all?" — whereas write gating is per-object ("is this user
    the owner of *this row*?").

    `assert_can_read(user)` is the raising form stored on the repository
    instance at request time; it fires before every `_get_by_id`, `_list`,
    and `_count` call. `can_read(user)` is the predicate form available for
    templates and other non-raising callers.

    Declare on `EntitySpec.read_policy`. `None` means open (default).
    Superuser bypass is the callable's responsibility — neither the
    framework nor `BaseRepository` short-circuits for superusers.
    """

    assert_can_read: Callable[[Any], None]
    can_read: Callable[[Any], bool]


@dataclass(frozen=True, slots=True)
class RouteSet:
    """Per-entity opt-in flags for which `mount_*` calls a route file makes."""

    list: bool = False
    detail: bool = False
    delete: bool = False
    create: bool = False
    update: bool = False
    form_new: bool = False
    form_edit: bool = False
    # `GET /<collection>/search` — the dedicated filter page. The
    # list page's toolbar links here ("Filter · N"); the form on this
    # page submits back to the list URL via GET. Read by
    # `mount_entity` → `mount_search`.
    search: bool = False


@dataclass(frozen=True, slots=True)
class StateAxis:
    """One state-axis subresource on an entity (e.g. `activation` on `user`).

    `handler_path` is a dotted import path (not a callable) so the spec
    module never imports from `src.logic`, preserving layer direction;
    `mount_entity` resolves it lazily via `importlib`.
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
    clinicians uses both.

    Per-field `None` means "default by convention" — `EntitySpec.__post_init__`
    fills it with ``f"{url_collection}/{verb}.html"`` for any verb the
    entity opts into via `RouteSet`. Specs only declare a field when the
    path diverges from the convention (no current entity does).
    """

    list: str | None = None
    detail: str | None = None
    form_new: str | None = None
    form_edit: str | None = None
    search: str | None = None


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
    """Declarative identity of a domain entity. `__post_init__`
    validates pairings that would otherwise leak silently at runtime."""

    # Identity ------------------------------------------------------------
    name: str
    url_collection: str
    id_param: str

    # Model + ownership --------------------------------------------------
    model: type
    # Human-facing singular for chrome strings — the noun that completes
    # "Create <X>" / "Edit <X>" on the form pages and every CTA that
    # opens them. Lowercase, no leading article; e.g. ``"organization"``,
    # ``"clinician"``, ``"opening"``. Defaults to ``name`` (most specs:
    # the URL singular doubles as the display noun); set explicitly when
    # the URL identifier diverges from the user-visible noun (e.g.
    # if a spec ever needed `name="thing_v2"` while showing "Thing" in
    # chrome, set this).
    #
    # `entity_create_label(name, kind=None)` reads this to build the
    # single canonical string the form-page H1 *and* every "Create X"
    # button render from — see `src/framework/templates/views/form_new.html`
    # and `src/framework/rendering/labels.py`. The pin test
    # `test_form_chrome_labels` asserts the structural equivalence.
    singular_label: str | None = None
    # Human-readable label for a single row of this entity — used by the
    # framework to auto-inject breadcrumb items on related-list and edge
    # pages. Return a short, user-visible string (e.g. a username, a full
    # name, an org name). Leave None for entities that never appear as a
    # parent in a URL ancestry chain.
    display_label_fn: Callable[[Any], str] | None = None
    owner_attr: str | None = "owner_id"

    # Parent (owned subentity link) --------------------------------------
    parent: "EntitySpec | None" = None
    # Subresource handlers (``handle_delete`` / ``handle_update``) enforce
    # URL-vs-row consistency so ``/parents/A/children/B`` cannot mutate a
    # child belonging to parent B. By default the check compares the
    # child's ``<parent.name>_id`` attribute to the URL's ``parent_id``.
    # Set this when the child's FK targets a *non-parent* table that the
    # parent also references — e.g. clinician credentials FK to
    # ``clinicians.id`` (#635 PR A) but URL-mount under ``/clinicians/...``.
    # When set, the framework loads the parent and compares
    # ``getattr(child, child_parent_match_attr) ==
    # getattr(parent, child_parent_match_attr)`` instead. The default
    # ``None`` keeps the cheap "child holds the FK directly" check.
    child_parent_match_attr: str | None = None
    # Override for the convention "child holds ``<parent.name>_id``" when
    # the FK column name diverges from the parent's entity name — e.g.
    # affiliations FK column is ``clinician_id``; the parent entity's
    # `name` is ``"clinician"``. Read by the same default-path branch in
    # ``handle_delete`` / ``handle_update`` ‑ a non-None value is used as
    # the attribute name on the child row, falling back to
    # ``f"{spec.parent.name}_id"`` when ``None``. Mutually orthogonal to
    # ``child_parent_match_attr``: that one swaps the comparison strategy
    # (child-attr vs parent-attr), this one only renames the child's
    # FK attr in the default strategy.
    parent_fk_attr: str | None = None

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
    # Capability gate for read access — the type-scoped complement to
    # `auth_policy` (which is per-object mutation). When set, `EntitySpec.__post_init__`
    # wraps `repo_dep` so the repository carries both the requesting user and
    # the guard callable into every read primitive (`_get_by_id`, `_list`,
    # `_count`). See `ReadPolicy` for the full contract.
    read_policy: "ReadPolicy | None" = None
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
    # repo defines `list_<collection>` (e.g. clinicians, with its
    # licensure-join filter) leave this `None` and the bespoke method
    # owns ordering inline.
    list_order_by: Any = None

    # List pagination size ---------------------------------------------
    # Per-page row count `handle_list` passes to the logic layer
    # (handler asks for `page_size + 1` rows and slices the probe off
    # to compute `has_next`). When `None`, falls back to
    # `src.framework.dispatch.pagination.DEFAULT_PAGE_SIZE`. Override
    # per entity when the row shape calls for it (e.g. posts' rich
    # `<li>` feed wants a smaller page than the clinicians table).
    page_size: int | None = None

    # Delete-route self guard ------------------------------------------
    # When True, `handle_delete` rejects the request with 403 if the
    # URL's target id equals the requesting user's id — preventing an
    # admin from deleting their own account. Symmetric to
    # `StateAxis.forbid_self`. Meaningful for user-shaped entities; on
    # owned resources the comparison never matches (target.id is a
    # row UUID, not a user id) so the flag is a no-op.
    delete_forbid_self: bool = False

    # List-page filters --------------------------------------------------
    # Each entry is either a raw ``QueryParam`` (URL-only declaration)
    # or a ``Filter`` (URL + UI metadata for the dedicated
    # ``/<collection>/search`` page). The mount layer normalizes both
    # to ``QueryParam`` before handing them to FastAPI; the list
    # handler echoes them into the template context so the
    # active-filter strip and the search-page form can render. See
    # ``filters.py``.
    filters: tuple[QueryParam | Filter, ...] = ()

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

    # Face shape of a polymorphic supertype. A spec carrying `discriminator`
    # picks one of three modes:
    #
    #   1. **kind-locked leaf** — `discriminator_value="<one kind>"`.
    #      The URL family is bound to a single kind; list forces
    #      `kind = <value>`, detail/update/delete/form_edit 404 unless
    #      `target.kind == <value>`, create's discriminated-union adapter
    #      (or per-kind adapter) sees the row as that kind, form_new
    #      skips the `?kind=` picker.
    #   2. **subset-supertype** — `discriminator_values=("<a>","<b>",...)`.
    #      The URL family lists rows whose kind is in the subset; detail/
    #      update/delete/form_edit 404 unless `target.kind in <subset>`;
    #      create takes `kind` in the body (discriminated-union adapter
    #      enforces membership); form_new requires `?kind=<one of subset>`.
    #      An umbrella URL that owns a strict subset of the supertype's
    #      kinds end-to-end; no URL family uses this mode today, but the
    #      dispatch handlers and `_make_factory_handler` support it.
    #   3. **whole-supertype** — both fields `None`. List takes any kind;
    #      `?kind=` query param picks the create-form template; the
    #      discriminated-union adapter handles dispatch on POST/PATCH.
    #      Used by `/posts`, which exposes every Post kind through a
    #      single URL family.
    #
    # `discriminator_value` and `discriminator_values` are mutually
    # exclusive. Both require `discriminator` to be set. Validated in
    # `__post_init__`. The column name read off the model is `Post.kind`
    # today — pinned by convention rather than spec-declared, since the
    # only consumer is the polymorphic post supertype.
    discriminator_value: str | None = None
    discriminator_values: tuple[str, ...] | None = None

    # Templates ----------------------------------------------------------
    templates: Templates = field(default_factory=Templates)

    # Form-error re-render opt-in ---------------------------------------
    # When True, the framework's `mount_create` catches 422 validation
    # errors from `parse_and_validate_form` on HX-Request POSTs and
    # re-renders the spec's form_new template with `form_errors` (dict
    # of field-name → first error message) and `form_values` (the raw
    # submitted payload) injected into the render context. Default
    # False preserves the JSON-422 contract for entities that haven't
    # opted in.
    #
    # Opted-in forms get the user-visible "inline error under each
    # invalid field, prefilled values" UX declaratively — the form
    # template only has to:
    #
    #   1. import the `_shared/form_fields.html` macros **`with context`**
    #      (so each macro can auto-resolve `error=` from
    #      `form_errors.get(name)` and `current=` from
    #      `form_values.get(name, current)` — see the docstring at the
    #      top of `_shared/form_fields.html`),
    #   2. set `hx-target="this" hx-swap="outerHTML"` on the `<form>`
    #      so the re-rendered partial replaces the form in place.
    #
    # No per-field error/value threading at the callsite — every
    # `field_for(...)` or direct input-macro call self-resolves from
    # the render context. Explicit caller args (`error=`/`current=`)
    # still win, so a form can override the auto-resolution where
    # needed.
    form_error_render: bool = False

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

    # Detail / list / form extras (per-viewer / per-list / per-form
    # customization) ----------------------------------------------------
    # `detail_extras_path`, `list_extras_path`, and `form_extras_path`
    # are dotted import paths (e.g.
    # `"src.domain.logic.users.handlers.user_detail_extras"`) to the
    # per-viewer extras callable consumed by `make_detail_handler` /
    # `make_list_handler` / `make_new_form_handler` +
    # `make_edit_form_handler`. The path is resolved lazily via
    # `importlib.import_module` + `getattr` at mount time, *after* both
    # the spec module and the logic module have been imported — so the
    # spec module never has to import from `src.logic.<entity>`, which
    # would close the cycle (logic modules import from the spec). Same
    # late-binding trick `StateAxis.handler_path` already uses.
    #
    # `detail_extras_repos` / `list_extras_repos` / `form_extras_repos`
    # declare typed repo kwargs the extras callable receives. Repository
    # classes live below specs in the import order, so the type-class
    # import is cycle-safe and the field carries real classes (not strings).
    #
    # The `form_extras_path` callable is invoked by *both* the create-form
    # and edit-form handlers; signature is
    # ``async def f(*, target: Model | None, requesting_user: User,
    # request: Request, <repo_kwargs>) -> dict[str, Any]``. ``target`` is
    # ``None`` on the create path and the loaded row on the edit path —
    # extras callables that need to pre-select the current row's values
    # (Org-picker, etc.) read it; create-only extras can ignore it. The
    # returned dict merges into the form template context (last-write-
    # wins, mirroring detail/list).
    detail_extras_path: str | None = None
    detail_extras_repos: tuple[tuple[str, type], ...] = ()
    list_extras_path: str | None = None
    list_extras_repos: tuple[tuple[str, type], ...] = ()
    form_extras_path: str | None = None
    form_extras_repos: tuple[tuple[str, type], ...] = ()

    # Write-time payload-FK authorization -------------------------------
    # `payload_authz_path` is a dotted import path to an async callable
    # invoked by `handle_create` / `handle_update` AFTER the parent /
    # target row has been loaded and `write_authz` (which gates the
    # target row itself) has run, and BEFORE the payload is used to
    # build / patch the model. Use it to gate FKs *referenced in the
    # payload* — e.g. "the requesting user must own the Org the
    # payload's `org_id` points at." This is distinct from `write_authz`,
    # which gates the target row; `payload_authz` runs in addition to,
    # not instead of, `write_authz`.
    #
    # Contract of the callable:
    #
    #   async def hook(
    #       *,
    #       payload: BaseModel,             # the validated create/update payload
    #       requesting_user: User,          # post-auth user
    #       **typed_repos,                  # one kwarg per entry in payload_authz_repos
    #   ) -> None:
    #       ...
    #
    # Raises `ForbiddenError` / `NotFoundError` on rejection; returns
    # `None` on success.
    #
    # Superuser bypass is the callable's responsibility. The framework
    # does NOT short-circuit when `requesting_user.is_superuser` — each
    # hook owns its own policy (e.g. "superusers may attach to any Org").
    #
    # `payload_authz_repos` declares typed repo kwargs the callable
    # receives. Mirrors `detail_extras_repos` exactly: repository
    # classes live below specs in the import order, so the type-class
    # import is cycle-safe and the field carries real classes (not
    # strings). The dotted-string `payload_authz_path` sidesteps the
    # remaining spec → logic cycle.
    #
    # Mount-time guard: declaring `payload_authz_path` alongside an
    # explicit `handlers["create"]` or `handlers["update"]` is rejected
    # by `mount_entity` — the explicit handler would silently bypass
    # the spec hook. Mirrors the existing `detail_extras_path` +
    # `handlers["detail"]` precedent.
    payload_authz_path: str | None = None
    payload_authz_repos: tuple[tuple[str, type], ...] = ()

    # `after_create_path` is a dotted import path to an async callable
    # invoked by `handle_create` AFTER the new row has been persisted
    # (it has an id) and BEFORE the audit `after`-snapshot is taken.
    # Use it to dispatch on payload fields and mutate the row's
    # server-controlled columns (the mutation flushes before the audit
    # snapshot, so the snapshot reflects the final state) OR to do
    # side effects in the same transaction (e.g. record a `Verification`
    # event, send an invite).
    #
    # Contract of the callable:
    #
    #   async def hook(
    #       *,
    #       row: <model>,                   # the just-persisted row
    #       payload: BaseModel,             # the validated create payload
    #       requesting_user: User,
    #       **typed_repos,                  # one kwarg per entry in after_create_repos
    #   ) -> None:
    #       ...
    #
    # Raises propagate; the framework's `mutate(...)` context manager
    # rolls back the transaction. The hook is for the factory-built
    # create path — declaring `after_create_path` alongside an explicit
    # `handlers["create"]` is rejected at mount time (same precedent as
    # `payload_authz_path`).
    #
    # `after_create_repos` declares typed-repo kwargs the callable
    # receives. Mirrors `payload_authz_repos` exactly.
    after_create_path: str | None = None
    after_create_repos: tuple[tuple[str, type], ...] = ()

    # `after_update_path` is the update-side mirror of `after_create_path`:
    # a dotted path to an async callable `handle_update` invokes AFTER the
    # row is patched and BEFORE the audit `after`-snapshot, inside the same
    # `mutate(...)` block. Unlike the create hook it also receives
    # `changed_fields: set[str]` — the column names whose value actually
    # changed — so it can react to real changes (e.g. re-run verification
    # only when `npi` differs).
    #
    #   async def hook(
    #       *,
    #       row: <model>,                   # the just-patched row
    #       payload: BaseModel,             # the validated update payload
    #       requesting_user: User,
    #       changed_fields: set[str],
    #       **typed_repos,                  # one kwarg per entry in after_update_repos
    #   ) -> None:
    #       ...
    #
    # Only fires on the non-polymorphic update path (the discriminator
    # branch patches a detail row and is left alone); declaring it on a
    # spec with a `discriminator` is rejected below.
    after_update_path: str | None = None
    after_update_repos: tuple[tuple[str, type], ...] = ()

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
        # Default `singular_label` to `name`. Specs only set the field
        # explicitly when the URL singular and the user-visible noun
        # diverge (none today; declared on the field so future
        # divergences have a place to land without touching templates).
        if self.singular_label is None:
            object.__setattr__(self, "singular_label", self.name)
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
        # `routes.search=True` without any declared `Filter` is dead —
        # the search page would render an empty form. Catch the misconfig
        # at import time.
        if self.routes.search:
            declared = [f for f in self.filters if isinstance(f, Filter)]
            if not declared:
                raise ValueError(
                    f"EntitySpec({self.name!r}) sets routes.search=True but "
                    "has no declared Filter — the /search page would be empty."
                )
        # State-axis names must be unique; route mounting iterates by
        # name, so duplicates would shadow each other silently.
        axis_names = [axis.name for axis in self.state_axes]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares duplicate state-axis "
                f"names: {axis_names}"
            )
        # A kind-locked face declares both `discriminator` (the supertype's
        # registry, needed for detail-model dispatch on create/update) and
        # `discriminator_value` (the single value this face is bound to).
        # `discriminator_value` without `discriminator` is incoherent — the
        # handler couldn't look up the per-kind detail model.
        if self.discriminator_value is not None and self.discriminator is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) sets discriminator_value="
                f"{self.discriminator_value!r} but no discriminator registry "
                "— a kind-locked face still needs the registry to look up "
                "its detail model on create/update."
            )
        # `discriminator_value` must be a value the registry knows about,
        # else create/update dispatch will KeyError at request time.
        if self.discriminator_value is not None:
            registry_names = self.discriminator.names
            if self.discriminator_value not in registry_names:
                raise ValueError(
                    f"EntitySpec({self.name!r}) sets discriminator_value="
                    f"{self.discriminator_value!r} but the discriminator "
                    f"registry only knows {registry_names!r}."
                )
        # `discriminator_value` set on an entity whose model lacks a
        # `kind` column is dead: the framework reads `target.kind` to
        # enforce the lock on detail/update/delete. Surface the misconfig
        # at import time.
        if self.discriminator_value is not None and not hasattr(self.model, "kind"):
            raise ValueError(
                f"EntitySpec({self.name!r}) sets discriminator_value="
                f"{self.discriminator_value!r} but model "
                f"{self.model.__name__} has no `kind` attribute — the "
                "framework reads `target.kind` to enforce the lock."
            )
        # `discriminator_values` (subset-supertype face) is mutually
        # exclusive with `discriminator_value` (kind-locked leaf face);
        # both refer to the same registry, but a face is either bound
        # to one kind or to a subset of kinds, never both.
        if (
            self.discriminator_values is not None
            and self.discriminator_value is not None
        ):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares both `discriminator_value` "
                f"({self.discriminator_value!r}) and `discriminator_values` "
                f"({self.discriminator_values!r}); they are mutually exclusive "
                "— a face is either kind-locked to one kind or scoped to a "
                "subset of kinds."
            )
        # Subset-supertype requires the registry; without it the handler
        # has no way to look up per-kind detail models on create/update.
        if self.discriminator_values is not None and self.discriminator is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) sets discriminator_values="
                f"{self.discriminator_values!r} but no discriminator registry "
                "— a subset-supertype face still needs the registry to look "
                "up per-kind detail models on create/update."
            )
        # Every member of `discriminator_values` must be a value the
        # registry knows about — else list/detail dispatch will KeyError
        # or 404 silently at request time.
        if self.discriminator_values is not None:
            registry_names = self.discriminator.names
            unknown = [v for v in self.discriminator_values if v not in registry_names]
            if unknown:
                raise ValueError(
                    f"EntitySpec({self.name!r}) sets discriminator_values="
                    f"{self.discriminator_values!r} but the discriminator "
                    f"registry only knows {registry_names!r}; unknown "
                    f"members: {unknown!r}."
                )
            if not self.discriminator_values:
                raise ValueError(
                    f"EntitySpec({self.name!r}) sets discriminator_values=() "
                    "— an empty subset is meaningless (the list would always "
                    "be empty)."
                )
        # `discriminator_values` set on a model without a `kind` column
        # is dead — same rationale as the `discriminator_value` guard.
        if self.discriminator_values is not None and not hasattr(self.model, "kind"):
            raise ValueError(
                f"EntitySpec({self.name!r}) sets discriminator_values="
                f"{self.discriminator_values!r} but model "
                f"{self.model.__name__} has no `kind` attribute — the "
                "framework reads `target.kind` to enforce the subset."
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
        # `read_policy` wraps `repo_dep` so the guard fires at the data layer.
        # The wrapped dep receives both the session-backed repo (via the original
        # dep) and the requesting user (via `current_active_user`), then stamps
        # both onto the repo instance before returning it. `BaseRepository._check_read`
        # fires before every `_get_by_id`, `_list`, and `_count` call.
        if self.read_policy is not None:
            if self.repo_dep is None:
                raise ValueError(
                    f"EntitySpec({self.name!r}) declares read_policy but no "
                    "repo_dep — the guard has no repository to attach to."
                )
            _guard = self.read_policy.assert_can_read
            _original_dep = self.repo_dep

            def _guarded_dep(
                repo: Any = Depends(_original_dep),
                user: Any = Depends(current_active_user),
            ) -> Any:
                repo._requesting_user = user
                repo._read_guard = _guard
                return repo

            object.__setattr__(self, "repo_dep", _guarded_dep)
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
        if self.form_extras_path is not None and not (
            self.routes.form_new or self.routes.form_edit
        ):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares form_extras_path but "
                "neither routes.form_new nor routes.form_edit is True — "
                "the extras would never run."
            )
        if self.form_extras_repos and self.form_extras_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares form_extras_repos but "
                "no form_extras_path — the typed-repo kwargs would have "
                "no consumer."
            )
        # `payload_authz` runs from `handle_create` / `handle_update`;
        # declaring the path without either route is dead config (the
        # hook would never fire).
        if self.payload_authz_path is not None and not (
            self.routes.create or self.routes.update
        ):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares payload_authz_path but "
                "neither routes.create nor routes.update is True — the "
                "hook would never run."
            )
        if self.payload_authz_repos and self.payload_authz_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares payload_authz_repos but "
                "no payload_authz_path — the typed-repo kwargs would have "
                "no consumer."
            )
        # `after_create` only fires from `handle_create`; declaring the
        # path without `routes.create=True` is dead config.
        if self.after_create_path is not None and not self.routes.create:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares after_create_path but "
                "routes.create is False — the hook would never run."
            )
        if self.after_create_repos and self.after_create_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares after_create_repos but "
                "no after_create_path — the typed-repo kwargs would have "
                "no consumer."
            )
        # `after_update` only fires from `handle_update`'s non-polymorphic
        # path; declaring it without `routes.update=True`, with leftover
        # repos, or on a polymorphic spec is dead/unsupported config.
        if self.after_update_path is not None and not self.routes.update:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares after_update_path but "
                "routes.update is False — the hook would never run."
            )
        if self.after_update_repos and self.after_update_path is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares after_update_repos but "
                "no after_update_path — the typed-repo kwargs would have "
                "no consumer."
            )
        if self.after_update_path is not None and self.discriminator is not None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares after_update_path with a "
                "discriminator — the polymorphic update path patches a detail "
                "row and does not run the hook. Not supported."
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
            "search": self.templates.search,
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
            or r.search
        )

    @property
    def declared_filters(self) -> tuple["Filter", ...]:
        """`Filter` instances declared on this spec (excluding raw
        `QueryParam`); what the `/search` page renders and what the
        active-filter strip iterates."""
        return tuple(f for f in self.filters if isinstance(f, Filter))

    @property
    def children(self) -> tuple["EntitySpec", ...]:
        """Owned-subentity specs whose ``parent`` is this entity.

        Populated automatically as children declare ``parent=self``;
        order matches the children's construction order. Returned as a
        tuple so callers cannot mutate the underlying registry.

        Consumers: the generic ``handle_create`` walks
        ``spec.children`` so the standard top-level create path appends
        inline-child rows automatically (clinicians' credential lists).
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
            form_template=self.templates.form_new,
            create_redirect=self.create_redirect,
            update_redirect=self.update_redirect,
            delete_redirect=self.delete_redirect,
            private_fields=self.private_fields,
            private_field_predicate=self.private_field_predicate,
            parent=parent_rs,
            form_error_render=self.form_error_render,
            entity_spec=self,
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
# follow this rule (clinician, post, all three credentials) declare
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


# Re-exported here so existing `from src.framework.dispatch.entity_spec import Redirects`
# callers keep working. The canonical definition lives in redirects.py.
from src.framework.dispatch.redirects import Redirects  # noqa: E402
