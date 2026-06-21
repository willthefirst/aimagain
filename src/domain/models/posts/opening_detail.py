from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "opening_details"


class OpeningDetail(Base):
    """1:1 detail row for posts of kind = 'clinician_opening'.

    The opening is a **self-describing announcement**: it carries its own
    delivery format (``session_format``), service lines (``services`` /
    ``services_other_text``, on the same ``ReferralService`` vocabulary
    referrals use), the cohort it's for (``age_groups`` / ``genders``),
    ``cost``, plus ``schedule_text`` / ``description`` and the two context
    FKs (``clinician_id``, ``clinician_affiliation_id``). This reverses the
    #1358 split for these dimensions — they're per-announcement, not
    per-affiliation — so a clinician can post two openings under the same
    affiliation targeting different cohorts/formats.

    The linked ``ClinicianAffiliation`` keeps only the steady-state context
    that doesn't vary per announcement: location (city/area + state),
    insurance posture, ``website`` / ``referral_instructions``, and the
    ``currently_accepting_new_patients`` cache. ``languages`` stays on the
    linked ``Clinician`` (a person attribute). See
    [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md).
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
    # practice's org name (no custom ``subject`` override) — aligning with
    # the referral model, which derives its headline.
    description = Column(Text, nullable=True)

    # Delivery format — any subset of {in_person, virtual}. Same JSON-list
    # shape + wire-only vocabulary check (`Literal[*SESSION_FORMATS]`) as
    # `ReferralDetail.session_format`; no SQL CHECK against array members.
    session_format = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Service lines offered, on the same `ReferralService` 12-leaf
    # vocabulary the referral request side uses (one "what care" axis for
    # both sides). The old provider-side `OpeningService` / settings /
    # modalities trio collapsed into this single list. `other` in the list
    # pairs with `services_other_text` (the uniform "Other → specify"
    # pattern; wired in `posts/conditional_fields.py`).
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    services_other_text = Column(Text, nullable=True)

    # Who this opening is for. Unlike referral's single-client `age_groups`
    # (capped at one bucket), an opening serves a cohort — multi-valued,
    # no cardinality CHECK. `genders` empty = "not stated".
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Per-announcement fee note (free text). Moved off the affiliation —
    # a practice may post different openings at different rates.
    cost = Column(Text, nullable=True)

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
