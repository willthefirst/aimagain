"""Single source of truth for post kinds.

`REGISTERED_KINDS` registers each kind's name, its per-kind detail
SQLAlchemy model, the relationship attribute on `Post` that points at
that detail, the detail row's user-facing fields, and the templates and
labels the route/template layers render for the kind.

Adding a kind requires:

1. A new entry in `REGISTERED_KINDS` here.
2. A new detail model under `src/models/<kind>_detail.py`, plus a
   `relationship(...)` line on `Post`.
3. The four Pydantic variant classes in `src/schemas/post.py`
   (Read, Create, Update, AuditSnapshot).
4. The `posts/new_<kind>.html` and `posts/edit_<kind>.html` templates.
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
"""

from dataclasses import dataclass
from typing import Final

from .client_referral_detail import ClientReferralDetail
from .provider_availability_detail import ProviderAvailabilityDetail


@dataclass(frozen=True)
class KindSpec:
    """Per-kind metadata. See module docstring for the registration contract."""

    name: str
    detail_model: type
    detail_relationship: str
    detail_fields: tuple[str, ...]
    list_label: str
    create_template: str
    edit_template: str


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


REGISTERED_KINDS: Final[dict[str, KindSpec]] = {
    "client_referral": KindSpec(
        name="client_referral",
        detail_model=ClientReferralDetail,
        detail_relationship="client_referral_detail",
        detail_fields=_detail_fields(ClientReferralDetail),
        list_label="client referral",
        create_template="posts/new_client_referral.html",
        edit_template="posts/edit_client_referral.html",
    ),
    "provider_availability": KindSpec(
        name="provider_availability",
        detail_model=ProviderAvailabilityDetail,
        detail_relationship="provider_availability_detail",
        detail_fields=_detail_fields(ProviderAvailabilityDetail),
        list_label="provider availability",
        create_template="posts/new_provider_availability.html",
        edit_template="posts/edit_provider_availability.html",
    ),
}

KIND_NAMES: Final[tuple[str, ...]] = tuple(REGISTERED_KINDS)

KIND_BY_DETAIL_MODEL: Final[dict[type, KindSpec]] = {
    spec.detail_model: spec for spec in REGISTERED_KINDS.values()
}


def kind_check_sql() -> str:
    """SQL fragment for the `posts.kind` CHECK constraint, derived from
    `KIND_NAMES`. Used by `models/post.py` at class-definition time so
    the constraint stays in lockstep with the registry."""
    return "kind IN (" + ", ".join(repr(k) for k in KIND_NAMES) + ")"
