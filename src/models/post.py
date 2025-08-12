from sqlalchemy import Column
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.schemas.post import PostType

from .base import BaseModel


class Post(BaseModel):
    __tablename__ = "posts"

    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    post_type = Column(SQLAlchemyEnum(PostType), nullable=False)
    created_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # SQLAlchemy relationships
    creator = relationship(
        "User", back_populates="created_posts", foreign_keys=[created_by_user_id]
    )
