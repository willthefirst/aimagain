"""POST_KINDS registry — see ./README.md for the cross-cutting consumer list."""

from dataclasses import dataclass
from typing import Final

from src.framework.persistence.polymorphic import DiscriminatorRegistry

from .intake_detail import IntakeDetail
from .opening_detail import OpeningDetail
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

    ``noun`` is the **canonical capital-case noun** for the kind — the
    SOT every user-facing reference to "what is this kind called" reads
    from: the /posts/form kind picker, the /posts sidebar `kind` filter
    options, and the Create / Edit / Filter page headlines (e.g.
    ``"Create Referral"`` / ``"Edit Opening"`` /
    ``"Create Program intake"``). Adding a kind or renaming one is a
    one-place change here.

    ``picker_description`` is the one-line tagline shown under the noun
    on /posts/form — written for the mental-health-provider audience.
    """

    name: str
    detail_model: type
    detail_relationship: str
    detail_fields: tuple[str, ...]
    noun: str
    picker_description: str
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
            noun="Referral",
            picker_description="Refer a client to another provider.",
        ),
        "clinician_opening": PostKindSpec(
            name="clinician_opening",
            detail_model=OpeningDetail,
            detail_relationship="opening_detail",
            detail_fields=_detail_fields(OpeningDetail),
            noun="Opening",
            picker_description=(
                "List an opening on your caseload and the kind of client "
                "you're looking to fill it with."
            ),
        ),
        "program_intake": PostKindSpec(
            name="program_intake",
            detail_model=IntakeDetail,
            detail_relationship="intake_detail",
            detail_fields=_detail_fields(IntakeDetail),
            noun="Program intake",
            picker_description=(
                "Announce open intake slots at a program your organization runs."
            ),
        ),
    },
)

POST_KIND_NAMES: Final[tuple[str, ...]] = POST_KINDS.names

POST_KIND_BY_DETAIL_MODEL: Final[dict[type, PostKindSpec]] = POST_KINDS.reverse_index(
    lambda spec: spec.detail_model,
)
