from functools import partial
from typing import ClassVar

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel
from src.framework.persistence.mixins import LocationMixin

from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, named_check_in

_TABLE = "clinician_affiliations"
_ck = partial(named_check_in, _TABLE)


class ClinicianAffiliation(LocationMixin, BaseModel):
    # Location is deferred during onboarding — users fill it in from the
    # "complete your profile" section after NPI verification.
    _location_nullable: ClassVar[bool] = True
    """The clinician's role at one organization.

    Holds the practice-role attributes that vary per (clinician × org):
    insurance posture, sliding-scale flag, cost, location, modality.
    Person attributes (npi, credentials) live on `Clinician`; org
    metadata lives on `Organization`. A clinician may hold multiple
    affiliations (one per org/role instance).

    Distinct from `OrgRepresentation` (User↔Org authority for Claim B
    of the two-claim verification model). The relationship attribute
    on `Clinician` stays `affiliations` since "the clinician's
    affiliations" reads naturally; only the model class + table got
    the disambiguating `Clinician` prefix.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinician = relationship(
        "Clinician", back_populates="clinician_affiliations", lazy="selectin"
    )

    # `org_id` is nullable: a solo clinician with no LLC has an
    # affiliation row whose `org_id` is NULL — the row still carries
    # their practice posture (location, availability, insurance, cost),
    # but there is no organizational entity to point at. See the
    # clinician-affiliations README for the "always ≥1 affiliation per
    # clinician" invariant and the stub-null-org case.
    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    org = relationship("Organization", lazy="selectin")

    # `in_person_sessions` / `virtual_sessions` are nullable: a stub
    # affiliation auto-created at verify time has not yet been asked
    # "do you see clients in person / virtually?" — NULL means "unset",
    # distinct from any of the LOCATION_AVAILABILITY_OPTIONS values.
    in_person_sessions = Column(Text, nullable=True)
    virtual_sessions = Column(Text, nullable=True)
    accepts_out_of_network = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )
    in_network_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    cost = Column(Text, nullable=True)

    # ----------------------------------------------------------------
    # Steady-state practice profile (#1358 PR-f, sub-PR 1).
    #
    # These columns are the new home for fields that previously lived
    # on `OpeningDetail` (the per-announcement row). The mental model
    # from #1358: *steady-state goes on Clinician/Affiliation; events
    # go on Post*. A clinician who reposts the same opening three
    # times in six months has *the same* services/settings/modalities/
    # age_groups/genders/website/referral_instructions across all three
    # — they're not per-announcement, they're per-affiliation.
    #
    # Sub-PR 1 (this PR) is purely additive: columns added with empty
    # defaults, backfilled from any existing OpeningDetail rows that
    # already attach to an affiliation via `clinician_affiliation_id`.
    # Reads still come from OpeningDetail; writes still dual to neither
    # site (the model accepts kwargs but the form/spec layers haven't
    # been flipped). Sub-PR 2 flips reads + adds dual-write; sub-PR 3
    # removes the columns from OpeningDetail.
    #
    # `languages` is deliberately NOT here — it moves to `Clinician`
    # (person attribute, invariant across affiliations) per #1358.
    # ----------------------------------------------------------------
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    modalities = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    website = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)

    # Denormalized accepting-new-patients flag. The source-of-truth
    # signal is "this affiliation has an active (not-closed)
    # OpeningDetail" but that's a join + state filter on every list
    # query. Cache it here so the directory list / filter UI can read
    # one column. The OpeningDetail lifecycle handlers will toggle
    # this in sub-PR 2 / 3; today it defaults to False and is left
    # untouched.
    currently_accepting_new_patients = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
