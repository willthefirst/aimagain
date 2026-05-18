from functools import partial

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel
from src.framework.persistence.mixins import LocationMixin

from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, named_check_in

_TABLE = "providers"
_ck = partial(named_check_in, _TABLE)

# `npi` is either NULL or exactly 10 ASCII digits — the NPPES registry
# lookups expect that shape. SQLite-flavored `GLOB`; the project is
# single-dialect (sqlite+aiosqlite for both dev and prod). The Pydantic
# validator `_validate_npi` in `src/domain/logic/providers/schema.py` is
# the primary wire-side enforcement; this CHECK is defense-in-depth.
_NPI_FORMAT_CHECK = CheckConstraint(
    "npi IS NULL OR (length(npi) = 10 "
    "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
    name=f"ck_{_TABLE}_npi_format",
)


class Provider(LocationMixin, BaseModel):
    """Long-lived provider directory entry. Owns the provider's credential
    lists (licensures, educations, certifications) via cascade. A user may
    own multiple `Provider` rows — `uq_provider_profiles_user_id` was
    dropped in `8f20a93effc9` to allow it — so the `owner_id` FK is
    intentionally non-unique. Distinct from `OpeningDetail`,
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
        _NPI_FORMAT_CHECK,
    )

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user = relationship("User")
    # `provider.org.name` is the practice's display name — there is no
    # separate `practice_name` column.
    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    org = relationship("Organization", back_populates="providers", lazy="selectin")
    # National Provider Identifier — 10 ASCII digits, optional. Nullable
    # because backfill is operator-driven (existing rows ship without one).
    # No UNIQUE constraint yet — duplicates may exist before the field is
    # curated; a follow-up can tighten this once data is clean.
    npi = Column(Text, nullable=True)
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)

    # Insurance posture. `in_network_carriers` is the set of carriers the
    # practice accepts in-network — an empty list means "no in-network".
    # `accepts_out_of_network` is independent: a practice may accept
    # in-network, out-of-network, both, or neither (self-pay only).
    # Default is `True` — most practices accept OON, and forcing the
    # opt-out matches the real-world prior.
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

    @property
    def org_name(self) -> str | None:
        """Convenience accessor for ``provider.org.name`` — the practice's
        display name. Used by ``ProviderRead`` (via ``from_attributes``)
        and templates that want a `None`-safe read when the relationship
        is unloaded. Returns ``None`` only in the narrow window where
        ``org`` hasn't been populated yet (pre-flush ORM constructions);
        every persisted row has a NOT NULL ``org_id``."""
        return self.org.name if self.org is not None else None
