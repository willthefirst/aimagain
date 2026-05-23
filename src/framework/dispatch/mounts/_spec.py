"""`QueryParam` and `ResourceSpec` dataclasses.

`ResourceSpec` is the narrow per-mount input — `EntitySpec` (the
upstream declaration) bridges to it via `to_resource_spec()` at mount
time. The mount functions read knobs from here.
"""

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter

from src.framework.audit.core import AuditedResource

# Sentinel used by `QueryParam.required()` to distinguish "no default
# supplied" from "default is None". Also consumed by `_synth.py` when
# materializing the FastAPI `Query(...)` default.
_UNSET = object()


@dataclass(frozen=True)
class QueryParam:
    """Declarative query-param description for ``mount_list`` / ``mount_form``.

    The mount adds it to the route's ``__signature__`` as a FastAPI
    ``Query(...)`` parameter so OpenAPI docs and 422-on-invalid validation
    work the same way they would on a hand-written route.

    Fields:
      name: kwarg name the mount passes to the handler.
      annotation: type annotation FastAPI uses for parsing/validation
        (``str | None``, ``Literal["a","b"]``, ``int``, etc.).
      default: default value if the param is omitted from the URL.
        Use ``QueryParam.required()`` to mark a param required.
      description: optional OpenAPI description.
    """

    name: str
    annotation: Any
    default: Any = None
    description: str = ""

    @classmethod
    def required(
        cls, name: str, annotation: Any, *, description: str = ""
    ) -> "QueryParam":
        """Mark a query param as required (no default)."""
        return cls(
            name=name, annotation=annotation, default=_UNSET, description=description
        )


@dataclass(frozen=True)
class ResourceSpec:
    """Declarative identity of a resource.

    The mount functions read knobs from here. Most fields default to
    `None` so a spec only declares what its mounted operations actually
    need; e.g. a read-only resource leaves `create_adapter` /
    `update_adapter` / `read_to_dict` unset.

    Fields:
      collection: URL segment (e.g. ``"users"``).
      id_param: name of the path param + handler kwarg for the resource
        id (e.g. ``"user_id"``).
      repo_dep: FastAPI ``Depends`` provider for the resource's primary
        repository. Mount functions inject this and pass it to handlers
        as ``repo=``.
      audit_resource: the ``AuditedResource`` bundle for ``mutate(...)``
        calls. Optional for read-only resources; required if the
        handler does any audited mutation.
      read_user_dep / write_user_dep: ``Depends`` providers for the
        authenticated user on read vs. write routes. ``None`` means
        public (no auth gate). Defaults to ``None`` so callers must
        opt in deliberately — silently public reads would be a bug.
      write_authz: optional callable invoked inside mutation handlers
        to enforce per-resource auth (e.g. ``assert_owner_or_admin``).
        Today the handler calls this itself; reserved on the spec for
        future centralization.
      create_adapter / update_adapter: ``TypeAdapter`` for form-encoded
        request bodies on POST/PATCH. Mount functions parse with
        ``parse_and_validate_form``.
      read_to_dict: callable that turns a persisted object into the
        response body for PATCH (and possibly other mounts later).
      list_template / detail_template / form_template: Jinja paths for
        read mounts. Polymorphic resources (e.g. posts kind-dispatch)
        may return ``template_name`` in the handler's context dict to
        override these per-request.
      (Additional repos beyond ``repo_dep`` are not declared on the
        spec — handlers spell each one out as a typed parameter and
        the mount layer resolves it via the type→resolver registry in
        ``src.framework.dependencies``.)
      create_redirect / update_redirect / delete_redirect: callables
        receiving the path params + (for create/update) the resource id,
        returning the ``HX-Redirect`` URL. ``None`` means use a sensible
        default per mount.
      private_fields: tuple of attribute names that are visible only to
        viewers for whom ``private_field_predicate(actor, target)`` is
        true. Empty tuple means no field-level gating; the resource is
        either fully public or fully gated by the route's auth dep.
        Read by ``src.framework.projections.project_view`` so the
        gating rule can be applied uniformly anywhere a view dict is
        built. Declaring private fields without a predicate raises at
        construction time.
      private_field_predicate: ``Callable[[actor, target], bool]``
        invoked by ``project_view`` to decide whether ``private_fields``
        should appear in the projected view. Required when
        ``private_fields`` is non-empty.
      parent: another ``ResourceSpec`` for sub-resources.
    """

    collection: str
    id_param: str
    repo_dep: Callable[..., Any]
    audit_resource: AuditedResource | None = None

    read_user_dep: Callable[..., Any] | None = None
    write_user_dep: Callable[..., Any] | None = None
    write_authz: Callable[..., None] | None = None

    create_adapter: TypeAdapter | None = None
    update_adapter: TypeAdapter | None = None
    read_to_dict: Callable[[Any], dict] | None = None

    list_template: str | None = None
    detail_template: str | None = None
    form_template: str | None = None

    create_redirect: Callable[..., str] | None = None
    update_redirect: Callable[..., str] | None = None
    delete_redirect: Callable[..., str] | None = None

    private_fields: tuple[str, ...] = ()
    private_field_predicate: Callable[..., bool] | None = None

    parent: "ResourceSpec | None" = None

    def __post_init__(self) -> None:
        # Field-level visibility metadata: `private_fields` names the
        # attributes gated by `private_field_predicate(actor, target)`.
        # Read by `src.framework.projections.project_view` (and any
        # future layer — JSON endpoint, audit snapshot, OpenAPI doc —
        # that needs to know which fields are private). Declaring fields
        # without a predicate would silently leak them, so require both
        # together.
        if self.private_fields and self.private_field_predicate is None:
            raise ValueError(
                f"ResourceSpec({self.collection!r}) declares private_fields="
                f"{self.private_fields!r} but no private_field_predicate — "
                "private fields cannot be gated without a predicate."
            )
