"""Tests for the post wire schemas.

Covers:
- The kind-discriminated union accepts each kind's payload and rejects
  unknown / missing `kind` values.
- Per-kind validation: non-empty stripping, partial-update at-least-one
  rule, server-managed-field rejection, unknown-field rejection.
- `post_audit_snapshot` projects a SQLAlchemy `Post` of any registered
  kind through the right snapshot class.
"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.schemas.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)

# --- PostCreate (discriminated union) -----------------------------------


def test_post_create_dispatches_client_referral():
    p = post_create_adapter.validate_python(
        {"kind": "client_referral", "description": "needs a clinician"}
    )
    assert isinstance(p, ClientReferralCreate)
    assert p.kind == "client_referral"
    assert p.description == "needs a clinician"


def test_post_create_requires_kind():
    """`kind` is required — no default fallback."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"description": "needs help"})


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_create_rejects_retired_note_kind():
    """The `note` kind was removed; payloads sending it must 422."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "note", "title": "hi", "body": "there"}
        )


def test_post_create_strips_surrounding_whitespace_client_referral():
    p = post_create_adapter.validate_python(
        {"kind": "client_referral", "description": "  help  "}
    )
    assert p.description == "help"


def test_post_create_client_referral_rejects_empty_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "client_referral", "description": "   "}
        )


def test_post_create_client_referral_requires_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "client_referral"})


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {
                "kind": "client_referral",
                "description": "d",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_post_create_rejects_unknown_fields_on_client_referral():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


# --- PostUpdate (discriminated union) -----------------------------------


def test_post_update_client_referral_accepts_description():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "fresh"}
    )
    assert isinstance(p, ClientReferralUpdate)
    assert p.description == "fresh"


def test_post_update_requires_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"description": "x"})


def test_post_update_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_update_rejects_retired_note_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "note", "title": "x"})


def test_post_update_strips_whitespace_client_referral():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "  hi  "}
    )
    assert p.description == "hi"


def test_post_update_client_referral_requires_description():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": None}
        )


def test_post_update_client_referral_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "   "}
        )


def test_post_update_client_referral_rejects_owner_id():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "client_referral",
                "description": "d",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_post_update_client_referral_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


# --- post_audit_snapshot ------------------------------------------------


def test_audit_snapshot_for_client_referral_post():
    owner_id = uuid.uuid4()
    post = SimpleNamespace(
        kind="client_referral",
        owner_id=owner_id,
        client_referral_detail=SimpleNamespace(description="needs a clinician"),
    )
    assert post_audit_snapshot(post) == {
        "kind": "client_referral",
        "description": "needs a clinician",
        "owner_id": str(owner_id),
    }


def test_audit_snapshot_unknown_kind_raises():
    """An unregistered kind fails the discriminator union — the audit
    helper surfaces it as a `ValidationError` (subclass of `ValueError`),
    not a silent partial snapshot."""
    post = SimpleNamespace(
        kind="not_a_kind",
        owner_id=uuid.uuid4(),
        client_referral_detail=None,
        provider_availability_detail=None,
    )
    with pytest.raises(ValidationError):
        post_audit_snapshot(post)


# --- provider_availability variants -------------------------------------


def test_post_create_dispatches_provider_availability():
    p = post_create_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "Acme Health"}
    )
    assert isinstance(p, ProviderAvailabilityCreate)
    assert p.kind == "provider_availability"
    assert p.practice_name == "Acme Health"


def test_post_create_strips_surrounding_whitespace_provider_availability():
    p = post_create_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "  Acme  "}
    )
    assert p.practice_name == "Acme"


def test_post_create_provider_availability_rejects_empty_practice_name():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "provider_availability", "practice_name": "   "}
        )


def test_post_create_provider_availability_requires_practice_name():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "provider_availability"})


def test_post_create_rejects_unknown_fields_on_provider_availability():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {
                "kind": "provider_availability",
                "practice_name": "Acme",
                "evil": True,
            }
        )


def test_post_create_rejects_cross_kind_field_bleed():
    """Cross-kind field bleed must not validate."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {
                "kind": "provider_availability",
                "practice_name": "Acme",
                "description": "d",
            }
        )


def test_post_update_provider_availability_accepts_practice_name():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "Renamed"}
    )
    assert isinstance(p, ProviderAvailabilityUpdate)
    assert p.practice_name == "Renamed"


def test_post_update_provider_availability_strips_whitespace():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "  Renamed  "}
    )
    assert p.practice_name == "Renamed"


def test_post_update_provider_availability_requires_practice_name():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "provider_availability", "practice_name": None}
        )


def test_post_update_provider_availability_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "provider_availability", "practice_name": "   "}
        )


def test_post_update_provider_availability_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "provider_availability",
                "practice_name": "Acme",
                "evil": True,
            }
        )


def test_audit_snapshot_for_provider_availability_post():
    """Snapshotting a `kind='provider_availability'` post flattens through
    `provider_availability_detail`."""
    owner_id = uuid.uuid4()
    post = SimpleNamespace(
        kind="provider_availability",
        owner_id=owner_id,
        client_referral_detail=None,
        provider_availability_detail=SimpleNamespace(practice_name="Acme Health"),
    )
    assert post_audit_snapshot(post) == {
        "kind": "provider_availability",
        "practice_name": "Acme Health",
        "owner_id": str(owner_id),
    }
