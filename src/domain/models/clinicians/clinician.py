from sqlalchemy import CheckConstraint, Column, Text
from sqlalchemy.orm import relationship

from src.framework.persistence.base_model import BaseModel

_TABLE = "clinicians"

# `npi` is either NULL or exactly 10 ASCII digits — the NPPES registry
# lookups expect that shape. SQLite-flavored `GLOB`; the project is
# single-dialect (sqlite+aiosqlite for both dev and prod). The Pydantic
# validator `_validate_npi` in `src/domain/logic/providers/schema.py`
# is the wire-side enforcement; this CHECK is defense-in-depth and
# mirrors the constraint that previously lived on `providers.npi`
# (moved to `clinicians.npi` in the migration that introduced this
# table — see #629 PR 1).
_NPI_FORMAT_CHECK = CheckConstraint(
    "npi IS NULL OR (length(npi) = 10 "
    "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
    name=f"ck_{_TABLE}_npi_format",
)


class Clinician(BaseModel):
    """The person behind a directory entry — license-holder, name on
    NPPES, owner of credentials.

    Today a `Provider` (the directory listing) carries both the person
    attributes (NPI, licensures, education) and the practice-role
    attributes (insurance, sliding scale, location, modality). That
    fits a solo practitioner but breaks the multi-affiliation clinician
    (private practice + community-clinic Tuesdays + telehealth
    contracts). This entity is the first step of splitting those apart
    (issue #629 PR 1): `Clinician` holds the person attributes that
    are invariant across employers; `Provider` keeps the practice-role
    attributes for now and will become an `Affiliation` (clinician ×
    org) in PR 2.

    For PR 1 every existing `Provider` row has exactly one
    `Clinician` (1:1 backfill). The `clinician_id` FK on `Provider`
    is NOT NULL but not yet UNIQUE — so the framework is ready for
    PR 2's many-affiliations-per-clinician without an additional
    migration to drop a unique constraint.

    The directory's user-facing routes still read from `providers`;
    `Clinician.npi` is currently surfaced via the
    `Provider.clinician.npi` join in `ProviderRead`. The verification
    pipeline (NPPES lookup) reads through the same join — it didn't
    have a direct `Clinician` API before PR 1, and PR 1 leaves that
    boundary untouched.
    """

    __tablename__ = _TABLE
    __table_args__ = (_NPI_FORMAT_CHECK,)

    # National Provider Identifier — 10 ASCII digits, optional. Nullable
    # because backfill is operator-driven (rows existed before NPI
    # collection). No UNIQUE constraint yet — duplicates may exist
    # before the field is curated; tighten once the data is clean.
    npi = Column(Text, nullable=True)

    # Legal first / last name. Both nullable because existing rows
    # predate the columns (backfill is operator-driven, same posture as
    # `npi`). The verification pipeline reads through here for the
    # NPPES + OIG name match — without these, every check routes to
    # human review because the username fallback in `_clinician_names`
    # scores far below threshold (see `handlers.py:_clinician_names`).
    first_name = Column(Text, nullable=True)
    last_name = Column(Text, nullable=True)

    # Back-populates `Provider.clinician`. 1:many in the schema so PR 2
    # can attach more `Provider` rows (which become `Affiliation`s) to
    # one clinician without a relationship-cardinality migration. In
    # PR 1 each clinician has exactly one provider (the row it was
    # backfilled from).
    providers = relationship(
        "Provider",
        back_populates="clinician",
        cascade="all, delete-orphan",
    )

    # Person-level credential lists. FKs moved from `providers.id` to
    # `clinicians.id` in #635 PR A so a clinician's licenses /
    # educations / certifications follow them across affiliations.
    # CASCADE on the FK + delete-orphan here keeps the rows in
    # lockstep — deleting the clinician wipes the credential lists.
    # `Provider.licensures / educations / certifications` survive as
    # `@property` proxies into these relationships, so route handlers,
    # templates, and the framework's `repo.add_child(parent,
    # "licensures", licensure)` path keep working unchanged.
    licensures = relationship(
        "ProviderLicensure",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    educations = relationship(
        "ProviderEducation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    certifications = relationship(
        "ProviderCertification",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
