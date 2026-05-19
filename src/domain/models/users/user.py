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

    # Reverse of `Provider.owner_id`. The PA create form reads this off
    # `current_user` to populate the provider dropdown; `lazy="selectin"`
    # eager-loads all of the user's providers in a single query.
    providers = relationship(
        "Provider",
        foreign_keys="Provider.owner_id",
        lazy="selectin",
        viewonly=True,
    )
    # Reverse of `Program.owner_id`. Mirrors `providers` above — the
    # `intake` create form populates the Program-picker
    # dropdown from this.
    programs = relationship(
        "Program",
        foreign_keys="Program.owner_id",
        lazy="selectin",
        viewonly=True,
    )
