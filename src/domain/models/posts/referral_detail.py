from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

from ..enums import (
    US_STATES,
    named_check_in,
)

_TABLE = "referral_details"
_ck = partial(named_check_in, _TABLE)


class ReferralDetail(Base):
    """1:1 detail row for posts of kind = 'referral'.

    Carries ``(city, state)`` inline rather than via :class:`LocationMixin`
    — referrals don't model ZIP (they describe a client's region, not a
    postal address). ``ClinicianAffiliation`` keeps the full triple.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("location_state", US_STATES),)

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — client location (city + state; no ZIP on referrals)
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    # `session_format` is a JSON list — any subset of {in_person, virtual}.
    # Vocabulary check happens on the wire (Pydantic
    # `Literal[*SESSION_FORMATS]`); no SQL CHECK against JSON array
    # members, same pattern as `services` / `age_groups`.
    session_format = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 2 — demographics
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Pronouns the client goes by. JSON list of `PRONOUNS` tokens; empty
    # list = "not stated". Vocabulary check on the wire
    # (`Literal[*PRONOUNS]`); no SQL CHECK against JSON array members.
    pronouns = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Section 3 — subject / description
    subject = Column(Text, nullable=True)
    description = Column(Text, nullable=False)

    # Section 4 — services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    # Free-text describing the "Other" branch of `services` when the
    # referrer picks `other` in the multi-select. Nullable; the form
    # surfaces it as a textarea adjacent to the services list.
    services_other_text = Column(Text, nullable=True)

    # Section 5 — payment paths. Independent booleans; a single referral
    # may accept any subset.
    #
    #   * ``accepts_in_network`` — the patient has a carrier and wants
    #     the provider to bill it directly. Paired with
    #     ``insurance_carriers`` (multi-select; empty array allowed when
    #     the carrier is undecided / "any" / TBD).
    #   * ``accepts_private_pay`` — the patient is willing to pay
    #     out-of-pocket with no insurance involvement.
    #
    # Both default to ``False`` server-side; at least one is expected to
    # be true in practice, but the schema doesn't enforce that. The
    # unified ``INSURANCE_POSTURES`` view collapse (in
    # ``src/domain/logic/posts/view.py``) prioritizes
    # in-network → private-pay, and yields ``None`` when neither is set.
    accepts_in_network = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    accepts_private_pay = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    # Independent payment-path boolean — the provider offers reduced-fee
    # private pay tied to client need. Distinct from `accepts_private_pay`
    # (which only says "yes, the client will pay out of pocket").
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    # Free-text notes naming the carrier(s) the patient has when
    # ``accepts_in_network`` is true. Replaces the closed-vocab
    # ``insurance_carriers`` list — the corpus has too many regional
    # plans for a closed enum to keep up. Nullable; the form surfaces
    # it adjacent to the in-network checkbox.
    in_network_carrier_notes = Column(Text, nullable=True)
    # JSON array of `InsuranceCarrier` tokens; empty array means "no
    # carrier specified" (the typical shape when only private-pay is
    # accepted). Kept alongside `in_network_carrier_notes` for the
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
