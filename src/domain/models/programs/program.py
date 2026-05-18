from functools import partial

from sqlalchemy import Boolean, Column, Date, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import US_STATES, named_check_in

_TABLE = "programs"
_ck = partial(named_check_in, _TABLE)


class Program(BaseModel):
    """Structured treatment offering owned by an :class:`Organization` —
    e.g. an IOP cohort, a residential program, a day program. Distinct
    from :class:`Provider`, which is a clinician; a Program is the
    offering itself and may span multiple clinicians.

    ``state_preference`` is an explicit column on Program rather than a
    derived read of the parent Org's location — Programs may serve a
    different state than the Org's primary state (e.g. an Org in CA
    that runs a telehealth program for NY clients). The CHECK
    constraint mirrors Provider's ``location_state`` against
    :data:`US_STATES`.

    No insurance fields here — intentional grammar. Insurance is
    modeled on the Provider (who delivers care) and on the Post (the
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

    # The owning Organization. ``RESTRICT`` matches Provider.org_id —
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

    # Reverse of ``ProgramAvailabilityDetail.program_id``. Rarely traversed
    # from the Program side (templates dereference
    # ``post.program_availability_detail.program`` instead), but it pins
    # the cascade contract and keeps the back-populated symmetry explicit.
    program_availability_details = relationship(
        "ProgramAvailabilityDetail", back_populates="program"
    )

    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    # The US state the program serves. Independent from the parent
    # Org's primary state — see class docstring.
    state_preference = Column(Text, nullable=True)

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    # Defaults to True — most programs intake by default; opt-out is
    # the explicit choice. Matches the default-on shape used elsewhere
    # for boolean posture columns (e.g. Provider.accepts_out_of_network).
    accepting_referrals = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )

    @property
    def org_name(self) -> str | None:
        """Convenience accessor for ``program.organization.name``. Used
        by ``ProgramRead`` (via ``from_attributes``) so templates and
        audit snapshots can read a single flat string without
        dereferencing the relationship. ``None`` only in the narrow
        window where ``organization`` hasn't been loaded yet."""
        return self.organization.name if self.organization is not None else None
