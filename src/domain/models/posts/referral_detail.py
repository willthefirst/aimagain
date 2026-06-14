from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base
from src.framework.persistence.mixins import LocationMixin

from ..enums import (
    GENDERS,
    SESSION_FORMATS,
    US_STATES,
    named_check_in,
)

_TABLE = "referral_details"
_ck = partial(named_check_in, _TABLE)


class ReferralDetail(LocationMixin, Base):
    """1:1 detail row for posts of kind = 'referral'.

    Inherits ``(city, state, zip)`` location columns from
    :class:`LocationMixin`; the ``location_state`` CHECK constraint stays
    in ``__table_args__`` because CHECK names are table-prefixed.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("session_format", SESSION_FORMATS),
        _ck("gender", GENDERS),
    )

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — client location (city/state/zip from LocationMixin)
    # `session_format` is the collapsed referral-side replacement for
    # the previous two-axis (`location_in_person`, `location_virtual`)
    # shape. CHECK pins the vocabulary to `SESSION_FORMATS`. NOT NULL
    # with a server default of `either` so the migration backfill
    # tolerates rows whose old combination was ambiguous (defensive —
    # the migration's own backfill picks the right value first).
    session_format = Column(
        Text, nullable=False, server_default=text("'either'"), default="either"
    )
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 2 — demographics
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Gender identity of the referred client. NOT NULL with a
    # server-side default so the migration backfill picks up existing
    # rows. CHECK constraint above pins the vocabulary to `GENDERS`.
    gender = Column(Text, nullable=False, server_default=text("'prefer_not_to_say'"))

    # Section 3 — subject / description
    subject = Column(Text, nullable=True)
    description = Column(Text, nullable=False)

    # Section 4 — services. `treatment_modality` (the free-text scalar)
    # was dropped: the structured `modalities` enum list covers the
    # filterable shape and the free-text `description` covers prose,
    # so the scalar was duplicative on both axes.
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    modalities = Column(JSON, nullable=True, server_default=text("'[]'"), default=list)

    # Affirming-identity request constraints — symmetric to
    # `Clinician.affirming_identities`. JSON list of `AffirmingIdentity`
    # tokens; empty array means "none stated" (no preference). Vocabulary
    # check happens on the wire (Pydantic `Literal[*AFFIRMING_IDENTITIES]`);
    # no SQL CHECK against JSON array members, same pattern as `services`
    # / `age_groups` above.
    affirming_identities = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # License-class constraint on the referred provider. JSON list of
    # `LicenseType` tokens; empty array means "no constraint" (any license
    # class accepted). The corpus has recurring "psychiatrist OR PMHNP"
    # disjunctions that `services` can't express — `medication_management`
    # could be delivered by a PCP, PA, or non-psychiatric NP. License-class
    # is the cleaner cut. Same wire-side vocabulary check pattern as
    # `services` / `affirming_identities` — `Literal[*LICENSE_TYPES]` on
    # the Pydantic schema, no SQL CHECK against JSON array members.
    acceptable_license_types = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Clinical-niche tags — free-form request-side vocabulary (#1358 PR-c).
    # Symmetric to `Clinician.clinical_niches` on the provider side: the
    # referrer states the niches the client needs ("DGBI", "ADHD in women"),
    # the clinician claims the ones they cover. Deliberately NOT an enum —
    # the vocabulary is too open-ended on day one. Empty array = no
    # niche-specific constraint; matching is best-effort substring/exact
    # against the provider claim. See `Clinician.clinical_niches` for the
    # full design rationale.
    clinical_niches = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 5 — payment paths (#1358 PR-e). Three independent booleans
    # the corpus consistently distinguishes — "Anthem PPO; private pay
    # okay" combines two. Each path is independent: a single referral
    # may accept any subset of them, and not all subsets imply each
    # other (an in-network-only referrer may decline both OON-superbill
    # and private pay).
    #
    #   * ``accepts_in_network`` — the patient has a carrier and wants
    #     the provider to bill it directly. Paired with
    #     ``insurance_carriers`` (multi-select; empty array allowed when
    #     the carrier is undecided / "any" / TBD).
    #   * ``accepts_out_of_network_superbill`` — the provider is OON
    #     but a superbill is acceptable for the patient to seek
    #     reimbursement.
    #   * ``accepts_private_pay`` — the patient is willing to pay
    #     out-of-pocket with no insurance involvement.
    #
    # All three default to ``False`` server-side; at least one is
    # expected to be true in practice, but the schema doesn't enforce
    # that (a "no preference stated" form-submission with all three
    # false is shape-valid). The unified ``INSURANCE_POSTURES`` view
    # collapse (in ``src/domain/logic/posts/view.py``) prioritizes
    # in-network → out-of-network → private-pay → please_contact when
    # none is set.
    accepts_in_network = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    accepts_out_of_network_superbill = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    accepts_private_pay = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    # JSON array of `InsuranceCarrier` tokens; empty array means "no
    # carrier specified" (which is the natural shape when
    # ``accepts_in_network`` is false, but also valid when in-network is
    # accepted with no specific carrier preference). Vocabulary check
    # happens on the wire (Pydantic ``Literal[*INSURANCE_CARRIERS]``);
    # no SQL CHECK against JSON array members — same pattern as
    # ``services`` / ``age_groups`` above and
    # ``ClinicianAffiliation.in_network_carriers`` on the provider side.
    # The asymmetry between request-side scalar and provider-side list
    # is now fixed: both ends model the same shape.
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
