from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, event, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel
from src.framework.persistence.mixins import LocationMixin

from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, named_check_in

_TABLE = "affiliations"
_ck = partial(named_check_in, _TABLE)


class Affiliation(LocationMixin, BaseModel):
    """The clinician's role at one organization — second step of the
    `Provider` split (issue #629 PR 2).

    `Affiliation` holds the **practice-role attributes** that vary
    per (clinician × org): insurance posture, sliding-scale flag,
    cost, location, modality. The person attributes (`npi`,
    credentials) live on `Clinician`; the org metadata (name, type,
    parent) lives on `Organization`.

    PR 2 ships this table alongside `Provider`. Each existing
    `Provider` row is backfilled into one `Affiliation`, linked
    1:1 through the transitional ``provider_id`` UNIQUE FK so PR 3
    can switch the directory UI from reading `Provider` columns
    to reading `Affiliation` columns. PR 4 drops the per-role
    columns from `Provider` and the transitional FK once
    every reader has migrated.

    `(clinician_id, org_id)` is *not* declared UNIQUE — a clinician
    may eventually have multiple affiliations at the same org with
    different attributes (different rate / schedule / location). The
    direction we're moving toward is "one row per practice-role
    instance," and uniqueness is a curation problem, not a schema
    one.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
    )

    # FK back to the owning `providers` row. CASCADE so deleting the
    # Provider sweeps its affiliations with it. No longer UNIQUE
    # (dropped in `7c3c296c9429`, #642 PR 1) — a Provider can carry
    # multiple Affiliations; the clinician edit page surfaces them
    # as an inline list (same UX as licensures). Reads that still
    # need to dereference "the" affiliation per row use
    # `Provider.primary_affiliation`, which picks the oldest row by
    # `created_at`; PR 3 (this issue) collapses the directory listing
    # to one row per Clinician instead.
    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = relationship(
        "Provider",
        back_populates="affiliations",
        foreign_keys=[provider_id],
        lazy="selectin",
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinician = relationship("Clinician", lazy="selectin")

    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    org = relationship("Organization", lazy="selectin")

    # Practice-role attributes — mirror of the columns currently on
    # `providers`. The two tables hold the same data through the PR 2/
    # PR 3 transition; PR 3 switches reads to `affiliations` and PR 4
    # drops these columns from `providers`. The `(city, state, zip)`
    # triple comes from `LocationMixin`. After #642 PR 1 (the directory
    # re-platform) `clinician_id` is auto-filled from the parent
    # provider when an Affiliation is appended into
    # `Provider.affiliations` — see the event listener at the bottom
    # of this module.
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)
    accepts_out_of_network = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )
    in_network_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    cost = Column(Text, nullable=True)
    # Practice-area specialties — JSON list of strings (e.g. ["Trauma/PTSD",
    # "EMDR"]). Populated by the T5 be-findable wizard step. Nullable so
    # existing affiliations created before T5 (which set it via the migration
    # default '[]') keep working without a forced re-submission.
    specialties = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )


@event.listens_for(Affiliation.provider, "set")
def _inherit_clinician_id_from_provider(affiliation, provider, _oldvalue, _initiator):
    """When an Affiliation is attached to a Provider (either by direct
    assignment or by appending into `provider.affiliations`), default
    its ``clinician_id`` to the provider's so the wire payload doesn't
    need to carry the FK explicitly.

    Without this, the framework's generic create handler (``POST
    /providers/{id}/affiliations``) would have to either accept
    ``clinician_id`` on the wire (leaking an internal join) or be
    extended to peek at the parent — the listener keeps the contract
    "wire mirrors the user-facing form fields" intact.

    The listener never overwrites an explicit value (test fixtures
    that wire the join manually stay intact); the first
    ``Provider.__init__`` path also pre-populates ``clinician`` on the
    transient Affiliation directly so this listener is a no-op there.
    """
    if affiliation.clinician_id is None and provider is not None:
        clinician_id = getattr(provider, "clinician_id", None)
        if clinician_id is not None:
            affiliation.clinician_id = clinician_id
        else:
            clinician = getattr(provider, "clinician", None)
            if clinician is not None:
                affiliation.clinician = clinician
