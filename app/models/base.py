import uuid

from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy.types import Uuid


class BaseModel(declarative_base()):
    __abstract__ = True

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def created_at(cls):
        return Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )

    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )

    @declared_attr
    def deleted_at(cls):
        return Column(DateTime(timezone=True), nullable=True)


metadata = BaseModel.metadata
