from sqlalchemy import JSON, Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import BaseModel


class AuditLog(BaseModel):
    """Append-only record of every mutation per `RESOURCE_GRAMMAR.md:135`.

    Inherits `id` and `created_at` from BaseModel — `created_at` doubles as
    the audit row's `at` field. The inherited `updated_at` and `deleted_at`
    columns are present but never mutated (audit rows are immutable; the
    repository deliberately exposes no update/delete methods).

    `resource_id` is unconstrained by FK because `resource_type` varies
    (post, user, …) and SQLAlchemy doesn't model polymorphic FKs. Lookups
    are by `(resource_type, resource_id)` indexed pair if/when needed.
    """

    __tablename__ = "audit_log"

    actor_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Uuid(as_uuid=True), nullable=False)
    action = Column(Text, nullable=False)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
