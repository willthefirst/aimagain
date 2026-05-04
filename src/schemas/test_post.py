"""Schema tests for the kind-discriminated `/posts` payloads.

Pydantic validates `PostCreate` as a discriminated union on `kind`. These
tests exercise both kinds, confirm `extra="forbid"` rejects stray fields,
and confirm an unknown discriminator value is a 422 not a silent fallback.
"""

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from src.schemas.post import (
    ClientReferralCreate,
    PostCreate,
    ProviderAvailabilityCreate,
)

_post_create = TypeAdapter(PostCreate)


@pytest.mark.parametrize(
    "kind,expected_cls",
    [
        ("client_referral", ClientReferralCreate),
        ("provider_availability", ProviderAvailabilityCreate),
    ],
)
def test_post_create_dispatches_on_kind(kind, expected_cls):
    parsed = _post_create.validate_python({"kind": kind})
    assert isinstance(parsed, expected_cls)
    assert parsed.kind == kind


def test_post_create_rejects_missing_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({})


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({"kind": "not_a_real_kind"})


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
def test_post_create_rejects_extra_fields(kind):
    """`extra="forbid"` keeps stray fields (including the old title/body) out."""
    with pytest.raises(ValidationError):
        _post_create.validate_python({"kind": kind, "title": "no", "body": "no"})


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
def test_post_create_rejects_owner_id(kind):
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        _post_create.validate_python({"kind": kind, "owner_id": str(uuid.uuid4())})
