from sqlalchemy import JSON, Column, ForeignKey, Text, text
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

    Like the opening, the intake is **self-describing**: it carries its own
    service lines (``services`` / ``services_other_text``, on the
    ``ReferralService`` vocab), the cohort it serves (``age_groups`` /
    ``genders``), ``cost``, plus ``schedule_text`` / ``description`` and the
    ``program_id`` context FK. It carries no ``session_format`` — a Program
    is a single group offering with no per-announcement in-person/virtual
    axis. Only the steady-state context that doesn't vary per announcement —
    the Program name, ``state_preference``, ``languages``, ``website`` /
    ``referral_instructions``, owning Org — lives on the linked
    ``Program`` (see [`../programs/README.md`](../programs/README.md)).
    """

    __tablename__ = _TABLE

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # FK to the Program this announcement is for. The Program's name,
    # state preference, intake window, owning Org, and steady-state
    # context all live on the linked row — looked up via ``program.*``
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

    # Per-announcement narrative. The headline is derived from the linked
    # program's name (no custom subject override).
    description = Column(Text, nullable=True)

    # Service lines offered, on the same `ReferralService` 12-leaf vocab
    # the referral + opening sides use (one "what care" axis for every post
    # kind). `other` in the list pairs with `services_other_text`. Same
    # JSON-list shape + wire-only vocabulary check as the opening; no SQL
    # CHECK against array members.
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    services_other_text = Column(Text, nullable=True)

    # Who this intake is for. Multi-valued cohort (no cardinality CHECK,
    # unlike referral's single client). `genders` empty = "not stated".
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Per-announcement fee note (free text). A program may post different
    # intakes at different rates.
    cost = Column(Text, nullable=True)
