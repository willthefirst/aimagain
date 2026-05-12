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

    Mixed into :class:`~src.domain.models.providers.Provider` and
    :class:`~src.domain.models.posts.client_referral_detail.ClientReferralDetail`.
    Both consumers want ``nullable=False`` on all three columns and a
    ``location_state`` CHECK constraint against ``US_STATES``; the
    constraint stays on the consuming table (CHECK names are table-
    prefixed, see module docstring).

    Each column is declared via :func:`declared_attr` so SQLAlchemy
    builds a fresh :class:`Column` per subclass (a bare ``Column(...)``
    on a mixin would be shared across every consumer and only attach to
    the first table that imports it).

    The mixin also exposes a Python-side :attr:`location` property that
    returns a ``{"city": ..., "state": ..., "zip": ...}`` dict view of
    the three columns. The Read wire schema's nested ``location: Location``
    field consumes this property via Pydantic's ``from_attributes=True``;
    embedding schemas don't need to know about the underlying column
    layout.

    The wire/audit-layer counterpart is
    :class:`src.domain.logic.value_objects.location.Location`.
    """

    @declared_attr
    def location_city(cls):
        return Column(Text, nullable=False)

    @declared_attr
    def location_state(cls):
        return Column(Text, nullable=False)

    @declared_attr
    def location_zip(cls):
        return Column(Text, nullable=False)

    @property
    def location(self) -> dict[str, str]:
        """Python-side dict view of the ``(city, state, zip)`` columns.

        Consumed by the Read wire schema (``location: Location`` field
        with ``from_attributes=True``). The wire layer's
        ``model_serializer`` flattens this back to top-level
        ``location_<sub>`` keys on dump, so JSON/audit shape stays
        unchanged from pre-#451.
        """
        return {
            "city": self.location_city,
            "state": self.location_state,
            "zip": self.location_zip,
        }
