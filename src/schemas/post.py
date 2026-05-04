import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class PostRead(BaseModel):
    """Flat read projection of a `Post` + its kind-specific detail row.

    The wire shape stays flat (`title`, `body` at the top level) while the
    storage shape is parent + per-kind detail. The `model_validator` below
    flattens through `post.note_detail` when given a SQLAlchemy `Post`, so
    callers can do `PostRead.model_validate(post)` without knowing the
    parent/detail split.
    """

    id: uuid.UUID
    title: str
    body: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        if hasattr(data, "note_detail") and data.note_detail is not None:
            return {
                "id": data.id,
                "title": data.note_detail.title,
                "body": data.note_detail.body,
                "owner_id": data.owner_id,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


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


class PostAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for posts.

    Captures the user-meaningful fields that mutations to a `Post` can
    change. The id lives in `audit_log.resource_id` already, so it's not
    duplicated here.

    `title`/`body` live on `Post.note_detail` (the `kind='note'` detail
    row); the model-validator dereferences through the relationship so
    callers can pass a `Post` directly and don't have to know about the
    parent/detail split. Adding a field requires updating this class and,
    if it lives on a detail row, the validator below.
    """

    kind: str
    title: str
    body: str
    owner_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        if hasattr(data, "note_detail") and data.note_detail is not None:
            return {
                "kind": data.kind,
                "title": data.note_detail.title,
                "body": data.note_detail.body,
                "owner_id": data.owner_id,
            }
        return data
