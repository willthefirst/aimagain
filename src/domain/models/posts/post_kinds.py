"""POST_KINDS registry — see ./README.md for the cross-cutting consumer list."""

from dataclasses import dataclass
from typing import Final

from src.framework.persistence.polymorphic import DiscriminatorRegistry

from .opening_detail import OpeningDetail
from .program_availability_detail import ProgramAvailabilityDetail
from .referral_detail import ReferralDetail


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
        "referral": PostKindSpec(
            name="referral",
            detail_model=ReferralDetail,
            detail_relationship="referral_detail",
            detail_fields=_detail_fields(ReferralDetail),
            list_label="client referral",
        ),
        "opening": PostKindSpec(
            name="opening",
            detail_model=OpeningDetail,
            detail_relationship="opening_detail",
            detail_fields=_detail_fields(OpeningDetail),
            list_label="provider availability",
        ),
        "program_availability": PostKindSpec(
            name="program_availability",
            detail_model=ProgramAvailabilityDetail,
            detail_relationship="program_availability_detail",
            detail_fields=_detail_fields(ProgramAvailabilityDetail),
            list_label="program availability",
        ),
    },
)

POST_KIND_NAMES: Final[tuple[str, ...]] = POST_KINDS.names

POST_KIND_BY_DETAIL_MODEL: Final[dict[type, PostKindSpec]] = POST_KINDS.reverse_index(
    lambda spec: spec.detail_model,
)
