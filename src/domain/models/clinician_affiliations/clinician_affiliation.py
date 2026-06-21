from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import US_STATES, named_check_in

_TABLE = "clinician_affiliations"
_ck = partial(named_check_in, _TABLE)


class ClinicianAffiliation(BaseModel):
    """The clinician's role at one organization — steady-state context.

    Holds only what doesn't vary per announcement: where this clinician
    practices (``location_city`` / ``location_state``), the insurance
    posture (``accepts_out_of_network`` / ``in_network_carriers`` /
    ``sliding_scale``), how to refer (``website`` /
    ``referral_instructions``), and the ``currently_accepting_new_patients``
    cache. Everything that *is* per-announcement — service lines, delivery
    format, cohort served, cost — lives on ``OpeningDetail`` (the opening
    post), not here. Person attributes (npi, credentials, languages) live
    on ``Clinician``; org metadata on ``Organization``.

    Location mirrors ``ReferralDetail``: ``city`` is free-text "city or
    area" and there is no ZIP (a practice region, not a postal address).
    Both are nullable — location is deferred during onboarding (filled in
    from "complete your profile" after NPI verification).

    Distinct from ``OrgRepresentation`` (User↔Org authority for Claim B
    of the two-claim verification model). The relationship attribute on
    ``Clinician`` stays ``affiliations``; only the model class + table got
    the disambiguating ``Clinician`` prefix.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("location_state", US_STATES),)

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
    # their practice posture (location, insurance), but there is no
    # organizational entity to point at. See the clinician-affiliations
    # README for the "always ≥1 affiliation per clinician" invariant and
    # the stub-null-org case.
    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    org = relationship("Organization", lazy="selectin")

    # Location — city/area + state, no ZIP (matches `ReferralDetail`).
    # Both nullable: a stub affiliation auto-created at verify time hasn't
    # been asked the location question yet.
    location_city = Column(Text, nullable=True)
    location_state = Column(Text, nullable=True)

    # Insurance posture (steady-state — same across this clinician's
    # announcements at this org).
    accepts_out_of_network = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )
    in_network_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )

    # How to refer (steady-state).
    website = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)

    # Denormalized accepting-new-patients flag. The source-of-truth signal
    # is "this affiliation has an active (not-closed) OpeningDetail" but
    # that's a join + state filter on every list query. Cache it here so
    # the directory list / filter UI can read one column.
    currently_accepting_new_patients = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
