from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel
from src.framework.persistence.mixins import LocationMixin

from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, named_check_in

_TABLE = "providers"
_ck = partial(named_check_in, _TABLE)


class Provider(LocationMixin, BaseModel):
    """Long-lived provider directory entry. Owns the provider's credential
    lists (licensures, educations, certifications) via cascade. A user may
    own multiple `Provider` rows — `uq_provider_profiles_user_id` was
    dropped in `8f20a93effc9` to allow it — so the `owner_id` FK is
    intentionally non-unique. Distinct from `ProviderAvailabilityDetail`,
    which is a per-Post detail row tied to one outreach `Post`.

    Inherits the ``(city, state, zip)`` location columns from
    :class:`LocationMixin`. The ``location_state`` CHECK constraint lives
    in ``__table_args__`` below because CHECK names are table-prefixed.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
    )

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user = relationship("User")
    practice_name = Column(Text, nullable=False)
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)

    # Insurance posture (#449). `accepts_in_network` and
    # `accepts_out_of_network` are orthogonal Booleans — a practice may
    # accept either, both, or neither (self-pay only). `in_network_carriers`
    # is required-min-1 when `accepts_in_network=True`; must be empty
    # otherwise. The cross-field rule is enforced in the wire schema
    # (`ProviderCreate` / `ProviderUpdate`) — the model just records the
    # state.
    accepts_in_network = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    accepts_out_of_network = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    in_network_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    cost = Column(Text, nullable=True)

    licensures = relationship(
        "ProviderLicensure",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    educations = relationship(
        "ProviderEducation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    certifications = relationship(
        "ProviderCertification",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
