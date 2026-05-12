import uuid

from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Column, Text
from sqlalchemy.orm import relationship

from src.framework.persistence.base_model import BaseModel


class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",
    )

    # Reverse of `Provider.owner_id`. Templates that render the PA create
    # form read this off `current_user` to populate the provider dropdown;
    # `lazy="selectin"` so a single eager query loads all of the user's
    # providers when they reach the form (#448).
    providers = relationship(
        "Provider",
        foreign_keys="Provider.owner_id",
        lazy="selectin",
        viewonly=True,
    )
