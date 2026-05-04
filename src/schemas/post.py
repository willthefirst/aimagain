"""Wire schemas for posts.

`Post` is a parent row with a `kind` discriminator and a per-kind detail
table. The wire surface mirrors that shape: `PostCreate` / `PostUpdate`
/ `PostRead` / `PostAuditSnapshot` are kind-discriminated unions on the
(required) `kind` field. `kind` is required on every payload — the prep
PR (`require-kind-on-wire`) made that the contract before this PR added
a second kind.

`post_audit_snapshot(post)` validates a SQLAlchemy `Post` against the
union and returns a JSON-mode dump for the audit row.

`_KIND_DETAILS` is the single registry mapping each `kind` to its detail
relationship and detail-row fields. Adding a new kind means: (a) register
it here, (b) add the four schema variants (Read, Create, Update,
AuditSnapshot) and the discriminated unions below, (c) add a relationship
+ CHECK widening in `src/models/post.py`. The four variants share one
`_flatten_post_to_dict` helper so per-kind validators are 2 lines each.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

# --- Per-kind detail registry & shared flatten helper --------------------


_KIND_DETAILS: dict[str, tuple[str, tuple[str, ...]]] = {
    "note": ("note_detail", ("title", "body")),
    "client_referral": ("client_referral_detail", ("description",)),
}


def _flatten_post_to_dict(post) -> dict | None:
    """Flatten a SQLAlchemy `Post` (parent + per-kind detail) to a flat
    dict keyed on the parent + detail field names.

    Returns `None` when the input doesn't look like a `Post` (e.g. it's
    already a flat dict from a direct constructor call) so callers can
    fall back to passing the input through unchanged. Read variants and
    audit-snapshot variants share this helper; Pydantic silently drops
    fields that aren't declared on a given variant (neither Read nor
    AuditSnapshot uses `extra="forbid"`), so the same flat dict feeds
    both shapes.
    """
    kind = getattr(post, "kind", None)
    if kind not in _KIND_DETAILS:
        return None
    detail_attr, detail_fields = _KIND_DETAILS[kind]
    detail = getattr(post, detail_attr, None)
    if detail is None:
        return None
    return {
        "id": getattr(post, "id", None),
        "kind": kind,
        "owner_id": getattr(post, "owner_id", None),
        "created_at": getattr(post, "created_at", None),
        "updated_at": getattr(post, "updated_at", None),
        **{f: getattr(detail, f) for f in detail_fields},
    }


# --- Read projections ---------------------------------------------------


class _PostReadBase(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        return _flatten_post_to_dict(data) or data


class NoteRead(_PostReadBase):
    kind: Literal["note"]
    title: str
    body: str


class ClientReferralRead(_PostReadBase):
    kind: Literal["client_referral"]
    description: str


PostRead = Annotated[Union[NoteRead, ClientReferralRead], Field(discriminator="kind")]
post_read_adapter: TypeAdapter = TypeAdapter(PostRead)


# --- Create payloads ----------------------------------------------------


class NoteCreate(BaseModel):
    """Create payload for `kind='note'`."""

    kind: Literal["note"]
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


class ClientReferralCreate(BaseModel):
    """Create payload for `kind='client_referral'`. MVP: one field."""

    kind: Literal["client_referral"]
    description: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def _strip_and_require_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


PostCreate = Annotated[
    Union[NoteCreate, ClientReferralCreate], Field(discriminator="kind")
]
post_create_adapter: TypeAdapter = TypeAdapter(PostCreate)


# --- Update payloads (partial) ------------------------------------------


class NoteUpdate(BaseModel):
    kind: Literal["note"]
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
    def _at_least_one_field(self) -> "NoteUpdate":
        if self.title is None and self.body is None:
            raise ValueError("at least one of title, body must be provided")
        return self


class ClientReferralUpdate(BaseModel):
    kind: Literal["client_referral"]
    description: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def _strip_and_require_non_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ClientReferralUpdate":
        if self.description is None:
            raise ValueError("description must be provided")
        return self


PostUpdate = Annotated[
    Union[NoteUpdate, ClientReferralUpdate], Field(discriminator="kind")
]
post_update_adapter: TypeAdapter = TypeAdapter(PostUpdate)


# --- Audit snapshots ----------------------------------------------------


class _PostAuditSnapshotBase(BaseModel):
    owner_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        return _flatten_post_to_dict(data) or data


class NoteAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["note"]
    title: str
    body: str


class ClientReferralAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["client_referral"]
    description: str


PostAuditSnapshot = Annotated[
    Union[NoteAuditSnapshot, ClientReferralAuditSnapshot],
    Field(discriminator="kind"),
]
_post_audit_snapshot_adapter: TypeAdapter = TypeAdapter(PostAuditSnapshot)


def post_audit_snapshot(post) -> dict:
    """Build the audit `before`/`after` projection for a post of any kind.

    Validates `post` against the discriminated `PostAuditSnapshot` union
    — the `kind` discriminator picks the matching variant, which then
    flattens through the right detail relationship via the shared
    `_flatten_post_to_dict` helper. Adding a new `kind` only requires
    registering it in `_KIND_DETAILS` and adding its `*AuditSnapshot`
    variant to the union above.
    """
    return _post_audit_snapshot_adapter.validate_python(post).model_dump(mode="json")
