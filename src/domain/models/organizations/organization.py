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
    systems, and solo-practice shells. PR 1 of the Org/Program roadmap —
    standalone here; the migration of ``Provider.practice_name`` onto an
    ``org_id`` FK is a follow-up PR.

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
    parent = relationship(
        "Organization",
        remote_side="Organization.id",
        foreign_keys=[parent_org_id],
    )
    # Providers that belong to this Org. PR 2 of the roadmap (#520).
    # Cascade is FK-side ``RESTRICT`` (deleting an Org with Providers
    # fails loudly rather than silently orphaning); the ORM relationship
    # is read-only from the Org side. PR 3+ adds the create form that
    # picks an Org explicitly.
    providers = relationship("Provider", back_populates="org")
