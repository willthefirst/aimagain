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

    # Reverse of `Clinician.owner_id`. Lazy selectin so templates and
    # framework helpers that check `user.clinicians` don't need extra queries.
    clinicians = relationship(
        "Clinician",
        foreign_keys="Clinician.owner_id",
        lazy="selectin",
        viewonly=True,
    )
    programs = relationship(
        "Program",
        foreign_keys="Program.owner_id",
        lazy="selectin",
        viewonly=True,
    )
