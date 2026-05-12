from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel


class UserFavorite(BaseModel):
    """An edge from a user to a provider they have favorited. M:N: a user
    may favorite many providers and a provider may be favorited by many
    users. The pair `(user_id, provider_id)` is unique — re-favoriting is
    idempotent at the DB level. CASCADE on both FKs: deleting a user or
    provider removes their edges (no per-edge audit row on cascade; the
    user/provider delete is the audit trail).
    """

    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider_id", name="uq_user_favorites_user_provider"
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
    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    provider = relationship("Provider")
