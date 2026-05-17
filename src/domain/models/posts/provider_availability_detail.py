from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

_TABLE = "provider_availability_details"


class ProviderAvailabilityDetail(Base):
    """1:1 detail row for posts of kind = 'provider_availability'.

    Practice + location + delivery-format fields live on the linked
    `Provider` via `provider_id` (#448); insurance posture + sliding-scale
    + cost moved to `Provider` in #449. This row only carries fields that
    are *per-announcement*, not steady-state practice properties.
    """

    __tablename__ = _TABLE

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # FK to the practice this announcement is for. Practice name, location,
    # and delivery format all live on the linked `Provider` — looked up via
    # `provider.*` in templates and read projections.
    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = relationship("Provider", lazy="selectin")

    # Section 3 — availability
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    # Companion to `desired_times` for cohort dates / fixed program hours
    # (#442). The grid handles "what times of the week am I open"; this
    # captions "May 25 cohort, M-F 9-5". Both can coexist.
    schedule_text = Column(Text, nullable=True)

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Genders this practice serves. JSON-array of `GENDERS` tokens
    # (vocabulary enforced on the wire by Pydantic, not via SQL CHECK —
    # same shape as `services` / `settings` / `age_groups`). Empty list
    # is allowed both at rest and on the wire — "no restriction stated."
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Section 6 — about (free-text core fields)
    description = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
