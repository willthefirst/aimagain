from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel


class UserFavorite(BaseModel):
    """An edge from a user to a clinician they have favorited. M:N: a user
    may favorite many clinicians and a clinician may be favorited by many
    users. The pair `(user_id, clinician_id)` is unique — re-favoriting is
    idempotent at the DB level. CASCADE on both FKs: deleting a user or
    clinician removes their edges.
    """

    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "clinician_id", name="uq_user_favorites_user_clinician"
        ),
        Index(
            "ix_user_favorites_user_id_created_at",
            "user_id",
            "created_at",
        ),
    )

    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    clinician = relationship("Clinician")
