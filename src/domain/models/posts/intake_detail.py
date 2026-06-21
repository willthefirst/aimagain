from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "intake_details"


class IntakeDetail(Base):
    """1:1 detail row for posts of kind = 'program_intake'.

    The Program-level equivalent of :class:`OpeningDetail`. The Program
    announces intake openings as a *group offering* — the referrer is
    choosing an intake door (the Program) and trusting the Org to assign
    a clinician internally. Distinct from ``clinician_opening``, which
    names a specific clinician.

    After #1358 PR-f sub-3 this row is **thin by design**: it carries
    only per-announcement attributes (``schedule_text`` / ``description``)
    plus the ``program_id`` context FK. The steady-state profile (services,
    settings, modalities,
    age_groups, genders, languages, website, referral_instructions) lives
    on the linked ``Program`` — see
    [`../programs/README.md`](../programs/README.md).
    """

    __tablename__ = _TABLE

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # FK to the Program this announcement is for. The Program's name,
    # state preference, intake window, owning Org, and steady-state
    # profile all live on the linked row — looked up via ``program.*``
    # in templates and read projections. ``ondelete='CASCADE'`` mirrors
    # ``OpeningDetail.clinician_id``: deleting the Program tears down
    # its announcements with it (a post about a deleted Program is stale
    # by construction).
    program_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    program = relationship("Program", back_populates="intake_details", lazy="selectin")

    # Section 3 — availability
    schedule_text = Column(Text, nullable=True)

    # Per-announcement narrative — see :class:`OpeningDetail` for why the
    # ``subject`` / ``treatment_modality`` overrides were dropped.
    description = Column(Text, nullable=True)
