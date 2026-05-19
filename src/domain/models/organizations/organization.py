from functools import partial

from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import ORGANIZATION_TYPES, named_check_in

_TABLE = "organizations"
_ck = partial(named_check_in, _TABLE)


class Organization(BaseModel):
    """First-class directory entity for clinics, group practices, health
    systems, and solo-practice shells. ``Organization.name`` is the
    source of truth for the practice's display name; every Provider
    points at exactly one Org via ``Provider.org_id`` and templates
    read ``provider.org.name`` directly.

    Hierarchy is modeled as a self-referential tree via ``parent_org_id``
    (nullable; a root org has ``parent_org_id IS NULL``). ``root_org_id``
    is denormalized so subtree lookups stay one indexed read instead of
    a recursive CTE. See ``README.md`` in this directory for the
    insert-time invariant tying the two columns together.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("type", ORGANIZATION_TYPES),)

    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    root_org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    # ``lazy="selectin"`` so the detail template can resolve the parent's
    # *name* without re-issuing IO inside Jinja (async sessions disallow
    # implicit lazy-loads). Same pattern as ``Provider.org`` — any
    # relationship a template dereferences must be eagerly loaded at the
    # session boundary.
    parent = relationship(
        "Organization",
        remote_side="Organization.id",
        foreign_keys=[parent_org_id],
        lazy="selectin",
        join_depth=1,
    )
    # FK-side ``RESTRICT`` on Programs — deleting an Org with attached
    # Programs fails loudly rather than silently orphaning. The Org →
    # Provider path moved to Org → Affiliation in #635 PR B (the
    # `org_id` column was dropped from `providers`); callers that
    # want "providers at this org" now navigate `org.affiliations` and
    # read `affiliation.provider`. ORM relationships are read-only
    # from the Org side.
    programs = relationship("Program", back_populates="organization")
