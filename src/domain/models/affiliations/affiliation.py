from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
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

    # Transitional 1:1 link to the legacy `providers` row this
    # affiliation was backfilled from. UNIQUE so the join is
    # cardinality-safe for PR 3's reads. Dropped in PR 4 along
    # with the legacy `providers` table.
    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider = relationship(
        "Provider",
        back_populates="affiliation",
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
    # triple comes from `LocationMixin`.
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
