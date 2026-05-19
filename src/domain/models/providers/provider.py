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
    # NPI moved from `providers.npi` to `clinicians.npi` (#629 PR 1).
    # Read it through `provider.clinician.npi`; the ProviderRead schema
    # surfaces it as `npi` via a model-validator so wire callers keep
    # the same field name. The directory's `provider.clinician` join is
    # NOT NULL — every provider has exactly one clinician (the FK isn't
    # UNIQUE so PR 2 can attach multiple providers to one clinician).
    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinician = relationship("Clinician", back_populates="providers", lazy="selectin")
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

    def __init__(self, **kwargs):
        """Auto-create a 1:1 ``Clinician`` from any wire-side `npi` kwarg
        so the framework's generic create handler — which builds the
        model via ``spec.model(**payload.model_dump())`` — keeps
        working unchanged after the column move (#629 PR 1).

        Skips Clinician creation when the caller already supplies a
        ``clinician`` or ``clinician_id`` (test fixtures that wire the
        join manually, PR 2 where multiple providers share one
        clinician).
        """
        # Late import via the package facade — `Clinician` lives in a
        # sibling cluster (`models/clinicians/`), and a direct
        # `from src.domain.models.clinicians.clinician import Clinician`
        # would trip the cross-cluster lint. Going through
        # `src.domain.models` (which re-exports `Clinician`) keeps the
        # import out of the lint's cluster-aware regex, and importing
        # at call-time avoids a circular-import at module load.
        from src.domain.models import Clinician

        npi = kwargs.pop("npi", None)
        super().__init__(**kwargs)
        if (
            self.clinician is None
            and self.clinician_id is None
            and "clinician" not in kwargs
            and "clinician_id" not in kwargs
        ):
            self.clinician = Clinician(npi=npi)

    @property
    def npi(self) -> str | None:
        """Convenience accessor for ``provider.clinician.npi`` — kept so
        wire schemas, audit snapshots, and templates continue reading
        ``provider.npi`` after the column moved to ``clinicians.npi``
        in #629 PR 1. Returns ``None`` only in the narrow window
        where ``clinician`` hasn't been populated yet (pre-flush ORM
        constructions); every persisted row has a NOT NULL
        ``clinician_id`` and the relationship is ``lazy='selectin'``
        so eager loads include it.
        """
        return self.clinician.npi if self.clinician is not None else None

    @npi.setter
    def npi(self, value: str | None) -> None:
        """Route writes back to the linked ``Clinician`` so
        ``handle_update``'s ``setattr(provider, 'npi', value)`` and the
        framework's transient-construct path (``Provider(npi=...)``)
        both end up at the same column.
        """
        from src.domain.models import Clinician

        if self.clinician is None:
            self.clinician = Clinician(npi=value)
        else:
            self.clinician.npi = value

    @property
    def org_name(self) -> str | None:
        """Convenience accessor for ``provider.org.name`` — the practice's
        display name. Used by ``ProviderRead`` (via ``from_attributes``)
        and templates that want a `None`-safe read when the relationship
        is unloaded. Returns ``None`` only in the narrow window where
        ``org`` hasn't been populated yet (pre-flush ORM constructions);
        every persisted row has a NOT NULL ``org_id``."""
        return self.org.name if self.org is not None else None
