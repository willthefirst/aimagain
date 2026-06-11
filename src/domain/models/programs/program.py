from functools import partial

from sqlalchemy import JSON, Boolean, Column, Date, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import US_STATES, named_check_in

_TABLE = "programs"
_ck = partial(named_check_in, _TABLE)


class Program(BaseModel):
    """Structured treatment offering owned by an :class:`Organization` —
    e.g. an IOP cohort, a residential program, a day program. Distinct
    from :class:`Clinician`; a Program is the
    offering itself and may span multiple clinicians.

    ``state_preference`` is an explicit column on Program rather than a
    derived read of the parent Org's location — Programs may serve a
    different state than the Org's primary state (e.g. an Org in CA
    that runs a telehealth program for NY clients). The CHECK
    constraint mirrors Clinician's ``location_state`` against
    :data:`US_STATES`.

    No insurance fields here — intentional grammar. Insurance is
    modeled on the Clinician (who delivers care) and on the Post (the
    referral situation), not on the Program.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("state_preference", US_STATES),)

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user = relationship("User")

    # The owning Organization. ``RESTRICT`` matches Clinician affiliate org_id —
    # deleting an Org with Programs fails loudly rather than silently
    # orphaning them.
    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization = relationship(
        "Organization", back_populates="programs", lazy="selectin"
    )

    # Reverse of ``IntakeDetail.program_id``. Rarely traversed
    # from the Program side (templates dereference
    # ``post.intake_detail.program`` instead), but it pins
    # the cascade contract and keeps the back-populated symmetry explicit.
    intake_details = relationship("IntakeDetail", back_populates="program")

    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    # The US state the program serves. Independent from the parent
    # Org's primary state — see class docstring.
    state_preference = Column(Text, nullable=True)

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    # Defaults to True — most programs intake by default; opt-out is
    # the explicit choice. Matches the default-on shape used elsewhere
    # for boolean posture columns (e.g. Clinician.accepts_out_of_network).
    accepting_referrals = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )

    # ----------------------------------------------------------------
    # Steady-state Program profile (#1358 PR-f, sub-PR 1).
    #
    # Symmetric to the new columns on `ClinicianAffiliation` — see
    # `models/clinician_affiliations/clinician_affiliation.py` for the
    # full design rationale. These are the new home for fields that
    # previously lived on `IntakeDetail` (the per-announcement row for
    # a program). A Program's services / settings / modalities / age
    # groups / genders / languages / website / referral_instructions
    # don't change every time the Program reposts an intake window —
    # they're steady-state attributes of the offering itself.
    #
    # Sub-PR 1 is purely additive: columns added with empty defaults,
    # backfilled from any existing IntakeDetail rows attached to this
    # Program. Reads still come from IntakeDetail; writes still go to
    # IntakeDetail. Sub-PR 2 flips reads + dual-writes; sub-PR 3
    # removes the columns from IntakeDetail.
    #
    # `languages` lands here (and not only on Clinician) because a
    # Program is the offering, not a person — the Program's stated
    # language coverage is a property of the *program*, distinct from
    # whichever individual clinician picks up the case.
    # ----------------------------------------------------------------
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    modalities = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON,
        nullable=False,
        server_default=text("'[\"en\"]'"),
        default=lambda: ["en"],
    )
    website = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)

    # Denormalized accepting-new-patients flag — same role as the
    # column of the same name on `ClinicianAffiliation`. Distinct from
    # `accepting_referrals` above: `accepting_referrals` is the
    # operator's standing posture ("we generally take referrals"),
    # while `currently_accepting_new_patients` is the cached "we have
    # an active IntakeDetail right now" signal toggled by the
    # OpeningDetail/IntakeDetail lifecycle. Today it defaults to False
    # and stays untouched until sub-PR 2 / 3 wire the toggle.
    currently_accepting_new_patients = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )

    @property
    def org_name(self) -> str | None:
        """Convenience accessor for ``program.organization.name``. Used
        by ``ProgramRead`` (via ``from_attributes``) so templates and
        audit snapshots can read a single flat string without
        dereferencing the relationship. ``None`` only in the narrow
        window where ``organization`` hasn't been loaded yet."""
        return self.organization.name if self.organization is not None else None
