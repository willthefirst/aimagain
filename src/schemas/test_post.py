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
    NoteCreate,
    NoteUpdate,
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)

# --- PostCreate (discriminated union) -----------------------------------


def test_post_create_dispatches_note():
    p = post_create_adapter.validate_python(
        {"kind": "note", "title": "hi", "body": "there"}
    )
    assert isinstance(p, NoteCreate)
    assert p.kind == "note"


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
        post_create_adapter.validate_python({"title": "hi", "body": "there"})


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_create_strips_surrounding_whitespace_note():
    p = post_create_adapter.validate_python(
        {"kind": "note", "title": "  hi  ", "body": "  there  "}
    )
    assert p.title == "hi"
    assert p.body == "there"


def test_post_create_strips_surrounding_whitespace_client_referral():
    p = post_create_adapter.validate_python(
        {"kind": "client_referral", "description": "  help  "}
    )
    assert p.description == "help"


@pytest.mark.parametrize("field", ["title", "body"])
def test_post_create_note_rejects_empty_or_whitespace(field):
    payload = {"kind": "note", "title": "t", "body": "b", field: "   "}
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_client_referral_rejects_empty_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "client_referral", "description": "   "}
        )


@pytest.mark.parametrize("missing", ["title", "body"])
def test_post_create_note_requires_both_fields(missing):
    payload = {"kind": "note", "title": "t", "body": "b"}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_client_referral_requires_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "client_referral"})


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {
                "kind": "note",
                "title": "t",
                "body": "b",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_post_create_rejects_unknown_fields_on_note():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "note", "title": "t", "body": "b", "evil": True}
        )


def test_post_create_rejects_unknown_fields_on_client_referral():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


def test_post_create_rejects_note_fields_on_client_referral():
    """Cross-kind field bleed must not validate — `title`/`body` aren't on
    a client_referral."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "client_referral", "title": "t", "body": "b"}
        )


# --- PostUpdate (discriminated union) -----------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "note", "title": "new"},
        {"kind": "note", "body": "new"},
        {"kind": "note", "title": "t", "body": "b"},
    ],
)
def test_post_update_note_accepts_partial_fields(payload):
    p = post_update_adapter.validate_python(payload)
    assert isinstance(p, NoteUpdate)
    assert p.title == payload.get("title")
    assert p.body == payload.get("body")


def test_post_update_client_referral_accepts_description():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "fresh"}
    )
    assert isinstance(p, ClientReferralUpdate)
    assert p.description == "fresh"


def test_post_update_requires_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"title": "x"})


def test_post_update_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_update_strips_whitespace_note():
    p = post_update_adapter.validate_python({"kind": "note", "title": "  hi  "})
    assert isinstance(p, NoteUpdate)
    assert p.title == "hi"
    assert p.body is None


def test_post_update_strips_whitespace_client_referral():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "  hi  "}
    )
    assert p.description == "hi"


@pytest.mark.parametrize(
    "payload",
    [{"kind": "note"}, {"kind": "note", "title": None, "body": None}],
)
def test_post_update_note_requires_at_least_one_field(payload):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(payload)


def test_post_update_client_referral_requires_description():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": None}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "note", "title": "   "},
        {"kind": "note", "body": ""},
        {"kind": "note", "title": "t", "body": "   "},
    ],
)
def test_post_update_note_rejects_whitespace_only(payload):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(payload)


def test_post_update_client_referral_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "   "}
        )


def test_post_update_note_rejects_owner_id():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "note", "title": "t", "owner_id": str(uuid.uuid4())}
        )


def test_post_update_note_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "note", "title": "t", "evil": True}
        )


def test_post_update_client_referral_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


# --- post_audit_snapshot ------------------------------------------------


def test_audit_snapshot_for_note_post():
    """Snapshotting a `kind='note'` post flattens through `note_detail`."""
    owner_id = uuid.uuid4()
    post = SimpleNamespace(
        kind="note",
        owner_id=owner_id,
        note_detail=SimpleNamespace(title="t", body="b"),
        client_referral_detail=None,
    )
    assert post_audit_snapshot(post) == {
        "kind": "note",
        "title": "t",
        "body": "b",
        "owner_id": str(owner_id),
    }


def test_audit_snapshot_for_client_referral_post():
    owner_id = uuid.uuid4()
    post = SimpleNamespace(
        kind="client_referral",
        owner_id=owner_id,
        note_detail=None,
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
        note_detail=None,
        client_referral_detail=None,
    )
    with pytest.raises(ValidationError):
        post_audit_snapshot(post)
