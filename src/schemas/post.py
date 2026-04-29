import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class PostRead(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PostCreate(BaseModel):
    title: str
    body: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "body")
    @classmethod
    def _strip_and_require_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class PostUpdate(BaseModel):
    title: str | None = None
    body: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "body")
    @classmethod
    def _strip_and_require_non_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "PostUpdate":
        if self.title is None and self.body is None:
            raise ValueError("at least one of title, body must be provided")
        return self
