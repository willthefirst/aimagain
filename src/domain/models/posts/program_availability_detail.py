from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "program_availability_details"


class ProgramAvailabilityDetail(Base):
    """1:1 detail row for posts of kind = 'program_availability'.

    The Program-level equivalent of :class:`ProviderAvailabilityDetail`
    (#541). The Program announces intake openings as a *group offering* —
    the referrer is choosing an intake door (the Program) and trusting
    the Org to assign a clinician internally. Distinct from
    ``provider_availability``, which names a specific clinician.

    Field set mirrors :class:`ProviderAvailabilityDetail` one-to-one
    (description / referral_instructions / website / desired_times /
    schedule_text / services / settings / treatment_modality / age_groups
    / languages / genders); these are per-announcement attributes, not
    steady-state Program properties (the Program model already carries
    its name, description, state_preference, intake window, and
    accepting-referrals flag). The Program's owning Org name surfaces
    via ``program.organization`` for the templates.
    """

    __tablename__ = _TABLE

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # FK to the Program this announcement is for. The Program's name,
    # state preference, intake window, and owning Org all live on the
    # linked row — looked up via ``program.*`` in templates and read
    # projections. ``ondelete='CASCADE'`` mirrors
    # ``ProviderAvailabilityDetail.provider_id``: deleting the Program
    # tears down its announcements with it (a post about a deleted
    # Program is stale by construction).
    program_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    program = relationship(
        "Program", back_populates="program_availability_details", lazy="selectin"
    )

    # Section 3 — availability
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    schedule_text = Column(Text, nullable=True)

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Section 6 — about (free-text core fields)
    description = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
