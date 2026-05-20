from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

_TABLE = "providers"


# Per-role attributes that no longer live as columns on `providers` —
# they were dropped in #635 PR B and now live only on `affiliations`.
# The Provider constructor consumes them as kwargs and forwards them
# into a fresh `Affiliation`; the `@property` proxies below route
# reads and writes to `provider.primary_affiliation.X` so the
# framework's `repo.patch(provider, ...)` and the schema's
# `from_attributes` path keep working unchanged. A Provider may hold
# multiple Affiliations after #642 PR 1; the proxies always target
# the primary (oldest by `created_at`) — visual surfaces that still
# need to dereference "the" affiliation per row read through it. PR 3
# rolls the directory listing up by Clinician, after which the
# primary fallback only matters for the post-opening dropdown labels.
_PER_ROLE_ATTRS = (
    "org_id",
    "location_city",
    "location_state",
    "location_zip",
    "in_person_sessions",
    "virtual_sessions",
    "accepts_out_of_network",
    "in_network_carriers",
    "sliding_scale",
    "cost",
)


class Provider(BaseModel):
    """Long-lived provider directory entry.

    After #635 PR B `providers` is a thin structural table — it holds
    only `id`, `owner_id`, `clinician_id`, and the audit timestamps.
    Every per-role attribute (`org_id`, the `(city, state, zip)` triple,
    `in_person_sessions`, `virtual_sessions`, the insurance posture,
    `sliding_scale`, `cost`) lives on the linked
    :class:`~src.domain.models.affiliations.Affiliation` row.

    The Provider constructor splits incoming per-role kwargs out of the
    SQLAlchemy column constructor and forwards them into a transient
    `Affiliation` instead — so the framework's generic create handler
    (`spec.model(**payload.model_dump())`) keeps producing fully-wired
    rows from a wire-flat payload. That transient row becomes the
    Provider's first / primary `Affiliation`; the user may add more
    later via the inline list on the edit page (#642 PR 1). The
    `@property` proxies route reads and writes for those attrs through
    `provider.primary_affiliation.X`, so `repo.patch(provider, org_id=X)`
    and `ProviderRead.model_validate(provider)` both keep working
    unchanged — they target the primary affiliation.

    A user may own multiple `Provider` rows — `uq_provider_profiles_user_id`
    was dropped in `8f20a93effc9` to allow it — so the `owner_id` FK is
    intentionally non-unique. Distinct from `OpeningDetail`, which is a
    per-Post detail row tied to one outreach `Post`.
    """

    __tablename__ = _TABLE

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user = relationship("User")
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

    # 1:N link to the `Affiliation` rows that hold the per-role
    # attributes. Ordered by `created_at` (oldest first) so
    # ``primary_affiliation`` deterministically picks the original
    # affiliation as the "default" the directory listing reads through
    # — PR 3 collapses the listing to one row per Clinician, after
    # which the primary fallback only matters for the post-opening
    # form's dropdown (see `src/domain/templates/openings/_form.html`).
    affiliations = relationship(
        "Affiliation",
        back_populates="provider",
        order_by="Affiliation.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def primary_affiliation(self):
        """The Provider's "default" affiliation — the oldest row by
        ``created_at`` (which is also the original transient
        affiliation `Provider.__init__` built from the wire payload).

        Read paths that still need to dereference a single affiliation
        per row — the directory listing (until PR 3 rolls it up by
        Clinician), the post-opening form's dropdown labels — go
        through this property. The per-role `@property` proxies on
        Provider also delegate to it so existing read paths keep
        working unchanged.

        Returns ``None`` only in the narrow window where the Provider
        has no affiliations (pre-flush construction without per-role
        kwargs, or after every affiliation has been deleted)."""
        return self.affiliations[0] if self.affiliations else None

    # Credential sub-tables moved their FK from `providers.id` to
    # `clinicians.id` in #635 PR A — credentials are person-level.
    # `licensures` / `educations` / `certifications` survive as
    # `@property` proxies below so route handlers, templates, view-
    # models, and the framework's `repo.add_child(parent, "licensures",
    # ...)` path keep working unchanged: appending into the returned
    # collection appends to `clinician.licensures` (an SQLAlchemy
    # `InstrumentedList`) and sets the new row's `clinician_id`
    # automatically.

    def __init__(self, **kwargs):
        """Auto-create the side rows so the framework's generic
        ``spec.model(**payload.model_dump())`` create path keeps
        working unchanged through the multi-PR split (#629 / #635).

        - Any wire-side ``npi=`` / ``first_name=`` / ``last_name=``
          kwarg becomes a fresh ``Clinician`` attached as
          ``self.clinician`` (`npi` moved off ``providers`` in
          #629 PR 1; the name columns landed alongside it).
        - The per-role kwargs (``org_id``, ``location_*``,
          ``in_person_sessions``, ``virtual_sessions``,
          ``accepts_out_of_network``, ``in_network_carriers``,
          ``sliding_scale``, ``cost``) are peeled off `kwargs` and
          forwarded into a fresh ``Affiliation`` — those columns no
          longer exist on `providers` (#635 PR B). The Provider
          constructor itself sees only the structural columns
          (`owner_id`, `clinician_id`).

        Skips Clinician / Affiliation auto-create when the caller
        already supplies the relationship or its FK (test fixtures
        that wire the join manually).
        """
        # Late import via the package facade — sibling clusters
        # (`models/clinicians/`, `models/affiliations/`) can't be
        # imported directly per the cross-cluster lint. Going
        # through `src.domain.models` (which re-exports both)
        # keeps the import out of the lint's cluster-aware regex,
        # and importing at call-time avoids a circular import at
        # module load.
        from src.domain.models import Affiliation, Clinician

        npi = kwargs.pop("npi", None)
        first_name = kwargs.pop("first_name", None)
        last_name = kwargs.pop("last_name", None)
        # Peel per-role kwargs off before the SQLAlchemy column
        # constructor sees them — they target Affiliation now.
        per_role = {k: kwargs.pop(k) for k in list(_PER_ROLE_ATTRS) if k in kwargs}
        super().__init__(**kwargs)
        if (
            self.clinician is None
            and self.clinician_id is None
            and "clinician" not in kwargs
            and "clinician_id" not in kwargs
        ):
            self.clinician = Clinician(
                npi=npi, first_name=first_name, last_name=last_name
            )
        if not self.affiliations and "affiliations" not in kwargs:
            # Mirror the affiliation column defaults explicitly (column
            # `server_default`s only fire at flush) so the transient
            # row passes its NOT NULL columns. This becomes the
            # Provider's `primary_affiliation`; the user may later add
            # more affiliations via the inline list on the edit page
            # (#642 PR 1).
            self.affiliations = [
                Affiliation(
                    clinician=self.clinician,
                    org_id=per_role.get("org_id"),
                    location_city=per_role.get("location_city"),
                    location_state=per_role.get("location_state"),
                    location_zip=per_role.get("location_zip"),
                    in_person_sessions=per_role.get("in_person_sessions"),
                    virtual_sessions=per_role.get("virtual_sessions"),
                    accepts_out_of_network=per_role.get("accepts_out_of_network", True),
                    in_network_carriers=per_role.get("in_network_carriers") or [],
                    sliding_scale=per_role.get("sliding_scale", False),
                    cost=per_role.get("cost"),
                )
            ]

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

    # `first_name` / `last_name` — same proxy shape as `npi`. The
    # columns live on `Clinician` (one person, many affiliations); the
    # proxy here keeps `ProviderRead.model_validate(provider)` working
    # via `from_attributes` and `repo.patch(provider, first_name="X")`
    # landing on the linked clinician.
    @property
    def first_name(self) -> str | None:
        return self.clinician.first_name if self.clinician is not None else None

    @first_name.setter
    def first_name(self, value: str | None) -> None:
        from src.domain.models import Clinician

        if self.clinician is None:
            self.clinician = Clinician(first_name=value)
        else:
            self.clinician.first_name = value

    @property
    def last_name(self) -> str | None:
        return self.clinician.last_name if self.clinician is not None else None

    @last_name.setter
    def last_name(self, value: str | None) -> None:
        from src.domain.models import Clinician

        if self.clinician is None:
            self.clinician = Clinician(last_name=value)
        else:
            self.clinician.last_name = value

    # --- Per-role property proxies ----------------------------------
    # These delegate reads and writes to `provider.primary_affiliation.X`.
    # The actual columns were dropped from `providers` in #635 PR B;
    # the properties exist so:
    #
    #   * `ProviderRead.model_validate(provider)` keeps working (the
    #     schema reads `provider.org_id`, `provider.location_city`, etc.
    #     via `from_attributes`).
    #   * `repo.patch(provider, location_city="X")` lands on
    #     `primary_affiliation.location_city` because `_patch` calls
    #     `setattr(provider, "location_city", "X")`, which hits the
    #     property setter below.
    #   * Templates and `posts.view` callers that read
    #     `provider.location_city` directly keep working unchanged.

    @property
    def org_id(self):
        aff = self.primary_affiliation
        return aff.org_id if aff is not None else None

    @org_id.setter
    def org_id(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.org_id = value

    @property
    def org(self):
        """Proxy through `provider.primary_affiliation.org` so callers
        reading ``provider.org.name`` (templates, view models) keep
        working."""
        aff = self.primary_affiliation
        return aff.org if aff is not None else None

    @org.setter
    def org(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.org = value

    @property
    def org_name(self) -> str | None:
        """Convenience accessor for ``provider.org.name`` — the practice's
        display name. Used by ``ProviderRead`` (via ``from_attributes``)
        and templates that want a `None`-safe read when the relationship
        is unloaded. Returns ``None`` only in the narrow window where
        ``org`` hasn't been populated yet (pre-flush ORM constructions);
        every persisted row has a NOT NULL ``org_id``."""
        org = self.org
        return org.name if org is not None else None

    @property
    def location_city(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_city if aff is not None else None

    @location_city.setter
    def location_city(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_city = value

    @property
    def location_state(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_state if aff is not None else None

    @location_state.setter
    def location_state(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_state = value

    @property
    def location_zip(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_zip if aff is not None else None

    @location_zip.setter
    def location_zip(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_zip = value

    @property
    def in_person_sessions(self) -> str | None:
        aff = self.primary_affiliation
        return aff.in_person_sessions if aff is not None else None

    @in_person_sessions.setter
    def in_person_sessions(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.in_person_sessions = value

    @property
    def virtual_sessions(self) -> str | None:
        aff = self.primary_affiliation
        return aff.virtual_sessions if aff is not None else None

    @virtual_sessions.setter
    def virtual_sessions(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.virtual_sessions = value

    @property
    def accepts_out_of_network(self) -> bool | None:
        aff = self.primary_affiliation
        return aff.accepts_out_of_network if aff is not None else None

    @accepts_out_of_network.setter
    def accepts_out_of_network(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.accepts_out_of_network = value

    @property
    def in_network_carriers(self) -> list:
        aff = self.primary_affiliation
        if aff is None or aff.in_network_carriers is None:
            return []
        return aff.in_network_carriers

    @in_network_carriers.setter
    def in_network_carriers(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.in_network_carriers = value

    @property
    def sliding_scale(self) -> bool | None:
        aff = self.primary_affiliation
        return aff.sliding_scale if aff is not None else None

    @sliding_scale.setter
    def sliding_scale(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.sliding_scale = value

    @property
    def cost(self) -> str | None:
        aff = self.primary_affiliation
        return aff.cost if aff is not None else None

    @cost.setter
    def cost(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.cost = value

    @property
    def licensures(self):
        """Person-level credential list — proxies through
        `provider.clinician.licensures` after the FK move (#635 PR A).
        Returns the SQLAlchemy `InstrumentedList`, so `.append(...)`
        from `repo.add_child(parent, "licensures", row)` adds to the
        clinician's collection and the FK setter on
        `Clinician.licensures` populates `licensure.clinician_id`
        automatically."""
        return [] if self.clinician is None else self.clinician.licensures

    @property
    def educations(self):
        """Person-level credential list — see :py:attr:`licensures`."""
        return [] if self.clinician is None else self.clinician.educations

    @property
    def certifications(self):
        """Person-level credential list — see :py:attr:`licensures`."""
        return [] if self.clinician is None else self.clinician.certifications
