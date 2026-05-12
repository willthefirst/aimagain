"""Single source of truth for post kinds.

`POST_KINDS` registers each kind's name, its per-kind detail
SQLAlchemy model, the relationship attribute on `Post` that points at
that detail, the detail row's user-facing fields, and the templates and
labels the route/template layers render for the kind.

Adding a kind requires:

1. A new entry in `POST_KINDS` here — only the identity tuple (name,
   detail_model, detail_relationship, list_label) is required; template
   paths default to ``posts/new_<name>.html`` / ``posts/edit_<name>.html``.
2. A new detail model under `src/domain/models/posts/<kind>_detail.py`, plus a
   `relationship(...)` line on `Post`.
3. The four Pydantic variant classes in `src/schemas/post.py`
   (Read, Create, Update, AuditSnapshot).
4. The `posts/new_<kind>.html` and `posts/edit_<kind>.html` templates
   (the conventional names — declare an explicit `create_template=` /
   `edit_template=` on the spec only when the file path diverges).
5. An Alembic migration that creates the detail table and widens the
   `posts.kind` CHECK.

After that, every cross-cutting site reads from this registry: the
model's `CheckConstraint`, the route's `Literal` for the form `?kind=`
query parameter, the create/edit form-template dicts, the per-kind
flatten in `_patch_response_body` and `_flatten_post_to_dict`, the
repository's `_attach_detail` and `update_post`, and both logic-layer
dispatch ladders (`handle_create_post`, `handle_update_post`).

Removing a kind is the inverse: delete the registry entry, the detail
model + relationship, the four Pydantic classes, the templates, and ship
a migration that drops the detail table and narrows the CHECK. No edits
in routes, repositories, or logic.

The bookkeeping (names tuple, reverse-by-detail-model index, CHECK SQL
generator) is provided by the generic `DiscriminatorRegistry` in
`src/domain/models/_polymorphic.py`; this module only declares the
post-specific `PostKindSpec` shape and the registry instance.
"""

from dataclasses import dataclass
from typing import Final

from src.framework.polymorphic import DiscriminatorRegistry

from .client_referral_detail import ClientReferralDetail
from .provider_availability_detail import ProviderAvailabilityDetail


@dataclass(frozen=True)
class PostKindSpec:
    """Per-kind metadata. See module docstring for the registration contract.

    Template paths default by convention: ``posts/new_<name>.html`` for
    `create_template` and ``posts/edit_<name>.html`` for `edit_template`.
    Specs only declare an explicit path when the file diverges from the
    convention; today none does. The convention plus the directory listing
    under `src/domain/templates/posts/` is the single source of truth for what
    templates a kind ships.
    """

    name: str
    detail_model: type
    detail_relationship: str
    detail_fields: tuple[str, ...]
    list_label: str
    create_template: str | None = None
    edit_template: str | None = None

    def __post_init__(self) -> None:
        if self.create_template is None:
            object.__setattr__(self, "create_template", f"posts/new_{self.name}.html")
        if self.edit_template is None:
            object.__setattr__(self, "edit_template", f"posts/edit_{self.name}.html")


def _detail_fields(detail_model: type) -> tuple[str, ...]:
    """User-facing column names of a per-kind detail model.

    Excludes only the `post_id` PK/FK — every other column on the table
    is a wire-surface field. Sourcing this from the model itself rather
    than a hand-maintained tuple means adding/dropping a column is a
    one-place change: registry-driven flatten, audit snapshot, and
    PATCH response automatically pick it up. The
    `test_detail_fields_match_model_columns` guard in
    `test_post_kinds.py` keeps the convention honest if some future
    column ever needs to be excluded — drop the test or add an opt-out
    mechanism then, deliberately.
    """
    return tuple(c.name for c in detail_model.__table__.columns if c.name != "post_id")


POST_KINDS: Final[DiscriminatorRegistry[PostKindSpec]] = DiscriminatorRegistry(
    column="kind",
    specs={
        "client_referral": PostKindSpec(
            name="client_referral",
            detail_model=ClientReferralDetail,
            detail_relationship="client_referral_detail",
            detail_fields=_detail_fields(ClientReferralDetail),
            list_label="client referral",
        ),
        "provider_availability": PostKindSpec(
            name="provider_availability",
            detail_model=ProviderAvailabilityDetail,
            detail_relationship="provider_availability_detail",
            detail_fields=_detail_fields(ProviderAvailabilityDetail),
            list_label="provider availability",
        ),
    },
)

POST_KIND_NAMES: Final[tuple[str, ...]] = POST_KINDS.names

POST_KIND_BY_DETAIL_MODEL: Final[dict[type, PostKindSpec]] = POST_KINDS.reverse_index(
    lambda spec: spec.detail_model,
)
