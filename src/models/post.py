from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


class Post(BaseModel):
    __tablename__ = "posts"

    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner = relationship("User", lazy="joined")
