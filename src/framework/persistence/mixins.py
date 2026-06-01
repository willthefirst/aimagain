"""SQLAlchemy column-group mixins.

Home for column-group mixins shared by 2+ ORM models — the
DRY-at-the-model-layer counterpart to the Pydantic value objects in
``src/domain/logic/value_objects``. Mixins contribute columns; the
matching value object is the wire/audit-layer name for the same group.

Trigger to add a mixin here: the same set of columns (same names, types,
nullability) appears on 2+ tables and we want a named place to describe
that group. If only one table has the columns, just declare them on the
table. If the per-table types/nullabilities diverge, declare per-table
too — the mixin's only value is exact reuse.

Mixins **do not** declare CHECK constraints. Constraint names are
table-prefixed (``<table>_<column>_check``) so each consuming table
declares its own constraints in ``__table_args__``; the mixin only owns
the column declarations.
"""

from sqlalchemy import Column, Text
from sqlalchemy.orm import declared_attr


class LocationMixin:
    """``(city, state, zip)`` postal-address column group.

    Mixed into ORM models that carry a location triple.
    ``ReferralDetail`` keeps ``nullable=False`` (a referral is always
    location-specific).  ``ClinicianAffiliation`` sets
    ``_location_nullable = True`` so location can be deferred during
    onboarding and filled in later.

    Each column is declared via :func:`declared_attr` so SQLAlchemy
    builds a fresh :class:`Column` per subclass (a bare ``Column(...)``
    on a mixin would be shared across every consumer and only attach to
    the first table that imports it).

    The mixin exposes a Python-side :attr:`location` property that
    returns a ``{"city": ..., "state": ..., "zip": ...}`` dict when the
    columns are populated, or ``None`` when all three are ``NULL``.  The
    Read wire schema's nested ``location: Location | None`` field consumes
    this via Pydantic's ``from_attributes=True``.

    The wire/audit-layer counterpart is
    :class:`src.domain.logic.value_objects.location.Location`.
    """

    # Subclasses that allow NULL location (e.g. ClinicianAffiliation where
    # location is optional during onboarding) set this to True.  The
    # declared_attr methods read this at mapper-configuration time so
    # SQLAlchemy emits the right column definition per table.
    _location_nullable: bool = False

    @declared_attr
    def location_city(cls):
        return Column(Text, nullable=getattr(cls, "_location_nullable", False))

    @declared_attr
    def location_state(cls):
        return Column(Text, nullable=getattr(cls, "_location_nullable", False))

    @declared_attr
    def location_zip(cls):
        return Column(Text, nullable=getattr(cls, "_location_nullable", False))

    @property
    def location(self) -> dict[str, str | None] | None:
        """Python-side dict view of the ``(city, state, zip)`` columns.

        Returns ``None`` when all three columns are ``NULL`` — this lets
        the Read wire schema declare ``location: Location | None`` and
        correctly represent clinicians whose location has not been filled
        in yet.  When at least one column is non-NULL the full dict is
        returned so ``Location`` validation succeeds.
        """
        city = self.location_city
        state = self.location_state
        zip_ = self.location_zip
        if city is None and state is None and zip_ is None:
            return None
        return {"city": city, "state": state, "zip": zip_}
