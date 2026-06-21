from functools import partial

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

from ..enums import (
    US_STATES,
    named_check_in,
)

_TABLE = "referral_details"
_ck = partial(named_check_in, _TABLE)

# A referral describes a single client, so `age_groups` carries *at most
# one* bucket — unlike the multi-valued `age_groups` on openings/programs
# (which live on the linked affiliation/program, not here). The wire keeps
# the list shape (`RequiredAgeGroupsField`, exactly-one) so read/audit
# projections stay unchanged; this CHECK pins the cardinality in storage.
# This is a *cardinality* CHECK — distinct from the "vocabulary on the
# wire, no SQL CHECK against array *members*" convention the other JSON
# lists follow. `json_array_length` is valid in both SQLite (JSON1) and
# Postgres; migration `bf122208871b` uses the same function cross-dialect.
_ck_age_groups_single = CheckConstraint(
    "json_array_length(age_groups) <= 1",
    name=f"ck_{_TABLE}_age_groups_single",
)


class ReferralDetail(Base):
    """1:1 detail row for posts of kind = 'referral'.

    Carries ``(city, state)`` inline rather than via :class:`LocationMixin`
    — referrals don't model ZIP (they describe a client's region, not a
    postal address). ``ClinicianAffiliation`` keeps the full triple.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("location_state", US_STATES), _ck_age_groups_single)

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — client location (city + state; no ZIP on referrals)
    # `location_city` is nullable: a referral only needs a city for
    # in-person sessions. The conditional requirement (in-person →
    # city) is enforced on the wire by `REFERRAL_CONDITIONAL_RULES`
    # (`posts/conditional_fields.py`), not by a NOT NULL here.
    location_city = Column(Text, nullable=True)
    location_state = Column(Text, nullable=False)
    # `session_format` is a JSON list — any subset of {in_person, virtual}.
    # Vocabulary check happens on the wire (Pydantic
    # `Literal[*SESSION_FORMATS]`); no SQL CHECK against JSON array
    # members, same pattern as `services` / `age_groups`.
    session_format = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 2 — demographics
    # `age_groups` JSON list, capped at one bucket by the
    # `ck_referral_details_age_groups_single` CHECK above (a referral
    # describes a single client). Vocabulary still checked on the wire.
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Free-text "Other" branch of `languages` (a language outside the
    # closed `Language` enum). Mirrors `services_other_text`; nullable.
    # Conditional-required wiring: `posts/conditional_fields.py`.
    languages_other_text = Column(Text, nullable=True)
    # Pronouns the client goes by. JSON list of `PRONOUNS` tokens; empty
    # list = "not stated". Vocabulary check on the wire
    # (`Literal[*PRONOUNS]`); no SQL CHECK against JSON array members.
    pronouns = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    # Free-text "Other" branch of `pronouns`. Mirrors
    # `services_other_text`; nullable. See `posts/conditional_fields.py`.
    pronouns_other_text = Column(Text, nullable=True)

    # Section 3 — description. Referrals have no `subject` column: unlike
    # openings/intakes, the title is always derived from demographics +
    # services (`post_feed_headline`), never a poster-set custom string.
    description = Column(Text, nullable=False)

    # Section 4 — services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    # Free-text describing the "Other" branch of `services` when the
    # referrer picks `other` in the multi-select. Nullable; the form
    # surfaces it as a textarea adjacent to the services list.
    services_other_text = Column(Text, nullable=True)

    # Section 5 — payment paths.
    #
    # In-network has no boolean: a non-empty ``insurance_carriers`` list
    # *is* the in-network statement (the referrer names the carriers to
    # bill), mirroring the provider side where ``in_network_carriers``
    # carries the same signal. ``accepts_private_pay`` is an independent
    # opt-in for out-of-pocket clients. The unified ``INSURANCE_POSTURES``
    # view collapse (in ``src/domain/logic/posts/view.py``) reads
    # in-network off carrier presence, falls back to private-pay, and
    # yields ``None`` when neither is set.
    accepts_private_pay = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    # Independent payment-path boolean — the provider offers reduced-fee
    # private pay tied to client need. Distinct from `accepts_private_pay`
    # (which only says "yes, the client will pay out of pocket").
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    # Free-text "Other" branch of the `insurance_carriers` multi-select:
    # names carrier(s) not covered by the closed `InsuranceCarrier` enum.
    # Mirrors `services_other_text` for `services`. Nullable — an optional
    # free-text column; the form surfaces it adjacent to the carrier picker.
    # Conditional-required wiring lands in a follow-up PR.
    insurance_carriers_other_text = Column(Text, nullable=True)
    # JSON array of `InsuranceCarrier` tokens; empty array means "no
    # carrier specified" (the typical shape when only private-pay is
    # accepted). Kept alongside `insurance_carriers_other_text` for the
    # subset of carriers we *do* model as an enum.
    insurance_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 6 — referring clinician. FK to the Clinician row the
    # submitting user designates as the referrer. Nullable so existing
    # rows (created before this field existed) stay valid; the Create
    # schema requires it on new submissions.
    referring_clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="SET NULL"),
        nullable=True,
    )
    referring_clinician = relationship(
        "Clinician",
        foreign_keys=[referring_clinician_id],
        lazy="selectin",
    )

    # Context: the specific `ClinicianAffiliation` the referring clinician
    # is acting under. Mirrors `OpeningDetail.clinician_affiliation_id` —
    # a clinician with several org affiliations refers under one. Nullable
    # (null = no context set), `SET NULL` on affiliation delete.
    clinician_affiliation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinician_affiliations.id", ondelete="SET NULL"),
        nullable=True,
    )
    clinician_affiliation = relationship("ClinicianAffiliation", lazy="selectin")
