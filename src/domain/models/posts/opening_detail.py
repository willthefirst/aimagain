from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "opening_details"


class OpeningDetail(Base):
    """1:1 detail row for posts of kind = 'clinician_opening'.

    After #1358 PR-f sub-3 this row is **thin by design**: it carries only
    per-announcement attributes (``schedule_text`` / ``description``) plus
    the two context FKs (``clinician_id``, ``clinician_affiliation_id``).
    The steady-state
    practice profile (services, settings, modalities, age_groups, genders,
    languages, website, referral_instructions) lives on the linked
    ``ClinicianAffiliation`` (and ``languages`` on the linked
    ``Clinician``) — see
    [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md)
    for the migration history.
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

    schedule_text = Column(Text, nullable=True)

    # Per-announcement narrative. The headline is derived from the linked
    # practice's org name (no custom ``subject`` override), and modality is
    # read from the affiliation's structured ``modalities`` list (no
    # free-text ``treatment_modality`` override) — both dropped to align
    # with the referral model, which derives its headline and uses
    # controlled-vocabulary modality data.
    description = Column(Text, nullable=True)

    # Context: the specific `ClinicianAffiliation` this opening is offered
    # under. A clinician who affiliates with several orgs posts an opening
    # under one of them; this FK names which. Nullable — null means "no
    # context set" (the state of every row before this column existed and
    # of rows created before a picker populates it). `SET NULL` on delete
    # so removing an affiliation nulls the context rather than blocking.
    clinician_affiliation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinician_affiliations.id", ondelete="SET NULL"),
        nullable=True,
    )
    clinician_affiliation = relationship("ClinicianAffiliation", lazy="selectin")
