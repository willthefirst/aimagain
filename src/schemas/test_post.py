"""Schema tests for the kind-discriminated `/posts` payloads.

Pydantic validates `PostCreate` and `PostUpdate` as discriminated unions on
`kind`. These tests cover both kinds end-to-end on create, the new
`client_referral` field set (summary/urgency/region), and the partial-update
shape — including the at-least-one-field rule and `extra="forbid"`.
"""

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from src.schemas.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    PostCreate,
    PostUpdate,
    ProviderAvailabilityCreate,
)

_post_create = TypeAdapter(PostCreate)
_post_update = TypeAdapter(PostUpdate)


# --- Create dispatch -----------------------------------------------------


def test_post_create_dispatches_client_referral():
    parsed = _post_create.validate_python(
        {
            "kind": "client_referral",
            "summary": "needs day-program placement",
            "urgency": "medium",
            "region": "western mass",
        }
    )
    assert isinstance(parsed, ClientReferralCreate)
    assert parsed.summary == "needs day-program placement"
    assert parsed.urgency == "medium"
    assert parsed.region == "western mass"


def test_post_create_dispatches_provider_availability():
    parsed = _post_create.validate_python({"kind": "provider_availability"})
    assert isinstance(parsed, ProviderAvailabilityCreate)


def test_post_create_rejects_missing_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({})


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({"kind": "not_a_real_kind"})


# --- Create per-kind validation ------------------------------------------


@pytest.mark.parametrize("missing", ["summary", "urgency", "region"])
def test_client_referral_create_requires_field(missing):
    payload = {
        "kind": "client_referral",
        "summary": "s",
        "urgency": "low",
        "region": "r",
    }
    payload.pop(missing)
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_client_referral_create_rejects_bad_urgency():
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {
                "kind": "client_referral",
                "summary": "s",
                "urgency": "EXTREME",
                "region": "r",
            }
        )


@pytest.mark.parametrize("field", ["summary", "region"])
def test_client_referral_create_rejects_whitespace(field):
    payload = {
        "kind": "client_referral",
        "summary": "s",
        "urgency": "low",
        "region": "r",
        field: "   ",
    }
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_client_referral_create_strips_whitespace():
    parsed = _post_create.validate_python(
        {
            "kind": "client_referral",
            "summary": "  s  ",
            "urgency": "low",
            "region": "  r  ",
        }
    )
    assert isinstance(parsed, ClientReferralCreate)
    assert parsed.summary == "s"
    assert parsed.region == "r"


def test_post_create_rejects_extra_fields():
    """`extra="forbid"` keeps stray fields (including the old title/body) out."""
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {
                "kind": "client_referral",
                "summary": "s",
                "urgency": "low",
                "region": "r",
                "title": "no",
            }
        )


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {
                "kind": "client_referral",
                "summary": "s",
                "urgency": "low",
                "region": "r",
                "owner_id": str(uuid.uuid4()),
            }
        )


# --- Update --------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "client_referral", "summary": "new"},
        {"kind": "client_referral", "urgency": "high"},
        {"kind": "client_referral", "region": "new region"},
        {
            "kind": "client_referral",
            "summary": "s",
            "urgency": "low",
            "region": "r",
        },
    ],
)
def test_client_referral_update_accepts_partial(payload):
    parsed = _post_update.validate_python(payload)
    assert isinstance(parsed, ClientReferralUpdate)


def test_client_referral_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "client_referral"})


def test_client_referral_update_rejects_unknown_kind():
    """`provider_availability` has no Update variant yet."""
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "provider_availability"})


def test_client_referral_update_rejects_extra_fields():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "client_referral", "summary": "s", "evil": True}
        )


def test_client_referral_update_rejects_owner_id():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {
                "kind": "client_referral",
                "summary": "s",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_client_referral_update_rejects_whitespace_summary():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "client_referral", "summary": "   "})
