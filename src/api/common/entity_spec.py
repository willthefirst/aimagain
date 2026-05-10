"""`EntitySpec`: single declaration of a domain entity.

Phase 1 of the migration described in #317. Today the users vertical
declares its identity in three parallel places:

  - `USER_SPEC = ResourceSpec(...)` in `src/api/routes/users.py`
  - `USER = AuditedResource(...)` and `USER_PRIVATE_FIELDS` in
    `src/logic/users/user_processing.py`
  - mount-call state-axis arguments scattered around the route file

`EntitySpec` is the single source of truth those layer-level sites read
*from*. The mount helpers still consume `ResourceSpec`; an entity spec
derives one via :meth:`EntitySpec.to_resource_spec`. Phase 2 (a later
track) will introduce generation that binds directly against
`EntitySpec`; phase 1 just makes the declarations load-bearing without
changing any behavior.

The dataclass intentionally stops short of carrying handler references
on its state-axis / subresource descriptors: the spec sits in
`src/api/common/specs/` and pulling handlers in would mean
`api.common.specs` importing `src.logic.<entity>`, which is the
opposite of the usual layer direction and creates an import cycle with
handlers that read from the spec. Phase 1 keeps the spec as
*metadata*; route files supply the handler in the matching `mount_*`
call. Phase 2 can revisit once the cycle is broken structurally.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from src.api.common.resource_routes import ResourceSpec
from src.logic.audit import AuditAction, AuditedResource


@dataclass(frozen=True, slots=True)
class RouteSet:
    """Per-entity opt-in flags for which `mount_*` calls a route file makes.

    Phase 1 reads these for documentation/test purposes only — route
    files still call the mounts explicitly. Phase 2 will use them to
    drive auto-mounting.
    """

    list: bool = False
    detail: bool = False
    delete: bool = False
    create: bool = False
    update: bool = False
    form: bool = False


@dataclass(frozen=True, slots=True)
class StateAxis:
    """One state-axis subresource on an entity (e.g. `activation` on `user`).

    `handler` and `response_to_dict` are intentionally optional in
    phase 1: the route file passes the handler directly to
    `mount_state_axis`, because importing logic handlers into the spec
    module would invert the usual layer direction. Phase 2 will populate
    `handler` once the import direction is sorted.
    """

    name: str
    body_schema: type[BaseModel]
    action: AuditAction
    handler: Callable[..., Awaitable[Any]] | None = None
    response_to_dict: Callable[[Any], dict] | None = None


@dataclass(frozen=True, slots=True)
class Templates:
    """Static Jinja paths for the entity's read views."""

    list: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RelatedListSubresource:
    """A `GET /<entity>/{id}/<child.collection>` related-list subresource.

    `child_spec` is a `ResourceSpec` (not `EntitySpec`) so phase 1 can
    reference unmigrated entities — the providers-under-user related
    list points at the existing `PROVIDER_SPEC`. Subsequent A* PRs
    swap each child to the corresponding `EntitySpec`/`ResourceSpec`
    once the child is migrated.

    `handler` is omitted for the same reason as `StateAxis.handler`:
    the route file binds it at mount time.
    """

    child_spec: ResourceSpec
    template: str
    handler: Callable[..., Awaitable[Any]] | None = None
    singleton_alias: tuple[str, Callable[..., Any]] | None = None


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """Declarative identity of a domain entity.

    Read by:
      - Logic-layer handlers, for audit bindings and visibility rules
        (`USER_ENTITY.audit`, `USER_ENTITY.private_fields`,
        `USER_ENTITY.private_field_predicate`).
      - Route files, via :meth:`to_resource_spec` for the `mount_*`
        helpers, plus direct lookup for state-axis / subresource shape.
      - Spec-correctness tests (`src/api/common/specs/test_<entity>.py`)
        that assert the spec declares the right things.

    Construction validates pairings that would otherwise leak silently
    (e.g. `private_fields` without a predicate) — failing at import
    time is loud and immediate.
    """

    # Identity ------------------------------------------------------------
    name: str
    url_collection: str
    id_param: str

    # Model + ownership --------------------------------------------------
    model: type
    owner_attr: str | None = "owner_id"

    # FastAPI deps -------------------------------------------------------
    repo_dep: Callable[..., Any] | None = None
    read_user_dep: Callable[..., Any] | None = None
    write_user_dep: Callable[..., Any] | None = None

    # Audit --------------------------------------------------------------
    audit: AuditedResource | None = None

    # Visibility ---------------------------------------------------------
    private_fields: tuple[str, ...] = ()
    private_field_predicate: Callable[..., bool] | None = None

    # Route opt-ins ------------------------------------------------------
    routes: RouteSet = field(default_factory=RouteSet)

    # State axes + subresources -----------------------------------------
    state_axes: tuple[StateAxis, ...] = ()
    subresources: tuple[RelatedListSubresource, ...] = ()

    # Templates ----------------------------------------------------------
    templates: Templates = field(default_factory=Templates)

    def __post_init__(self) -> None:
        # Mirror `ResourceSpec.__post_init__` — declaring private fields
        # without a predicate would silently leak them.
        if self.private_fields and self.private_field_predicate is None:
            raise ValueError(
                f"EntitySpec({self.name!r}) declares private_fields="
                f"{self.private_fields!r} but no private_field_predicate — "
                "private fields cannot be gated without a predicate."
            )
        # State-axis names must be unique; route mounting iterates by
        # name, so duplicates would shadow each other silently.
        axis_names = [axis.name for axis in self.state_axes]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError(
                f"EntitySpec({self.name!r}) declares duplicate state-axis "
                f"names: {axis_names}"
            )

    def to_resource_spec(self) -> ResourceSpec:
        """Derive a `ResourceSpec` for the mount helpers.

        Phase 1 keeps `ResourceSpec` as the layer-of-glue that the
        existing `mount_*` functions consume. Route files do
        `USER_SPEC = USER_ENTITY.to_resource_spec()` and pass that to
        the mount calls — same call shapes, just the source of truth
        moves up one level.
        """
        return ResourceSpec(
            collection=self.url_collection,
            id_param=self.id_param,
            repo_dep=self.repo_dep,
            audit_resource=self.audit,
            read_user_dep=self.read_user_dep,
            write_user_dep=self.write_user_dep,
            list_template=self.templates.list,
            detail_template=self.templates.detail,
            private_fields=self.private_fields,
            private_field_predicate=self.private_field_predicate,
        )

    def state_axis(self, name: str) -> StateAxis:
        """Look up a state axis by name.

        Lets handlers read the audit `AuditAction` for a non-CRUD axis
        directly from the spec instead of hardcoding the enum:

            action=USER_ENTITY.state_axis("activation").action
        """
        for axis in self.state_axes:
            if axis.name == name:
                return axis
        raise KeyError(f"EntitySpec({self.name!r}) has no state axis named {name!r}")
