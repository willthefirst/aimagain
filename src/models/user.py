import uuid

from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Column, Text

from .base import BaseModel


class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",
    )
