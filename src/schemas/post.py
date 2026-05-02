"""Request/response schemas for `/posts` (kind-discriminated).

`Post` is polymorphic on `kind` (joined-table inheritance — see
`src/models/post.py`). Pydantic mirrors that with discriminated unions:
each kind has its own `*Create` / `*Read` / `*Update` schema, and
`PostCreate` / `PostRead` / `PostUpdate` are
`Annotated[Union[...], Field(discriminator="kind")]`. This gives FastAPI
a 422 with a clear pointer when an unknown `kind` arrives, and lets each
kind grow its own field set independently.

`kind` itself is server-set on creation (it's the discriminator). On
update the body must echo the same `kind` (the discriminator selects
which Update variant runs); the handler also enforces that the body's
`kind` matches the persisted post's kind, so a client can't repurpose a
post's identity via PATCH.

`provider_availability` carries no editable fields yet; only the create
variant exists. Once it grows fields, add a `ProviderAvailabilityUpdate`
to the `PostUpdate` union.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Create --------------------------------------------------------------


class _PostCreateBase(BaseModel):
    """Shared config for per-kind create payloads."""

    model_config = ConfigDict(extra="forbid")


_Urgency = Literal["low", "medium", "high"]


def _strip_required(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


class ClientReferralCreate(_PostCreateBase):
    kind: Literal["client_referral"]
    summary: str
    urgency: _Urgency
    region: str

    @field_validator("summary", "region")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)


class ProviderAvailabilityCreate(_PostCreateBase):
    kind: Literal["provider_availability"]


PostCreate = Annotated[
    Union[ClientReferralCreate, ProviderAvailabilityCreate],
    Field(discriminator="kind"),
]


# --- Update --------------------------------------------------------------


class _PostUpdateBase(BaseModel):
    """Shared config for per-kind PATCH payloads."""

    model_config = ConfigDict(extra="forbid")


class ClientReferralUpdate(_PostUpdateBase):
    """Partial update for a client_referral. All editable fields optional, but
    the schema rejects a no-op (no editable field set) at validation time."""

    kind: Literal["client_referral"]
    summary: str | None = None
    urgency: _Urgency | None = None
    region: str | None = None

    @field_validator("summary", "region")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_required(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ClientReferralUpdate":
        if all(
            getattr(self, name) is None for name in ("summary", "urgency", "region")
        ):
            raise ValueError(
                "at least one of summary, urgency, region must be provided"
            )
        return self


PostUpdate = Annotated[
    # Single-variant union for now; extend with `ProviderAvailabilityUpdate`
    # when that kind grows editable fields.
    Union[ClientReferralUpdate],
    Field(discriminator="kind"),
]


# --- Read ----------------------------------------------------------------


class _PostReadBase(BaseModel):
    """Shared fields that surface on every kind."""

    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClientReferralRead(_PostReadBase):
    kind: Literal["client_referral"]
    summary: str
    urgency: _Urgency
    region: str


class ProviderAvailabilityRead(_PostReadBase):
    kind: Literal["provider_availability"]


PostRead = Annotated[
    Union[ClientReferralRead, ProviderAvailabilityRead],
    Field(discriminator="kind"),
]


# --- Audit ---------------------------------------------------------------


class PostAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for posts.

    Captures the user-meaningful fields a `Post` mutation can change. Per-kind
    fields default to `None` for kinds that don't carry them, so a single
    snapshot shape covers every kind. Adding a field to this class flows
    through `_snapshot_post` automatically via `model_dump`.
    """

    kind: str
    owner_id: uuid.UUID
    summary: str | None = None
    urgency: str | None = None
    region: str | None = None

    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "ClientReferralCreate",
    "ClientReferralRead",
    "ClientReferralUpdate",
    "PostAuditSnapshot",
    "PostCreate",
    "PostRead",
    "PostUpdate",
    "ProviderAvailabilityCreate",
    "ProviderAvailabilityRead",
]
