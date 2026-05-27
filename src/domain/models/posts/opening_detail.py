from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "opening_details"


class OpeningDetail(Base):
    """1:1 detail row for posts of kind = 'clinician_opening'.

    Per-announcement fields live here. Practice-role attributes (location,
    insurance, modality) are on the linked `Clinician`'s primary
    `Affiliation`; this row carries only fields that are per-announcement,
    not steady-state practice properties.
    """

    __tablename__ = _TABLE

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    clinician = relationship("Clinician", lazy="selectin")

    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    schedule_text = Column(Text, nullable=True)

    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    subject = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
