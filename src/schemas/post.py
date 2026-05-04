"""Request/response schemas for `/posts` (kind-discriminated).

`Post` is polymorphic on `kind` (joined-table inheritance — see
`src/models/post.py`). Pydantic mirrors that with discriminated unions:
each kind has its own `*Create` and `*Read` schema, and `PostCreate` /
`PostRead` are `Annotated[Union[...], Field(discriminator="kind")]`. This
gives FastAPI a 422 with a clear pointer when an unknown `kind` arrives,
and lets each kind grow its own field set independently.

`kind` itself is server-set on creation (it's the discriminator), so it's
honored on the inbound payload but never accepted on a future PATCH —
identity, not state. There is no `*Update` schema in this PR because the
kinds carry no editable fields yet; PATCH and the edit form return when
the first per-kind fields land.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# --- Create --------------------------------------------------------------


class _PostCreateBase(BaseModel):
    """Shared config for per-kind create payloads."""

    model_config = ConfigDict(extra="forbid")


class ClientReferralCreate(_PostCreateBase):
    kind: Literal["client_referral"]


class ProviderAvailabilityCreate(_PostCreateBase):
    kind: Literal["provider_availability"]


PostCreate = Annotated[
    Union[ClientReferralCreate, ProviderAvailabilityCreate],
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


class ProviderAvailabilityRead(_PostReadBase):
    kind: Literal["provider_availability"]


PostRead = Annotated[
    Union[ClientReferralRead, ProviderAvailabilityRead],
    Field(discriminator="kind"),
]


# --- Audit ---------------------------------------------------------------


class PostAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for posts.

    Captures the user-meaningful, kind-agnostic fields a `Post` mutation can
    change. Per-kind fields will be added as they land — adding a field to
    this class flows through `_snapshot_post` automatically via `model_dump`.
    """

    kind: str
    owner_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "ClientReferralCreate",
    "ClientReferralRead",
    "PostAuditSnapshot",
    "PostCreate",
    "PostRead",
    "ProviderAvailabilityCreate",
    "ProviderAvailabilityRead",
]
