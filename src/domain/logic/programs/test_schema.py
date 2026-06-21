"""Schema validation for `Program` wire types.

The Read/Create/Update split mirrors the codebase's standard pattern;
the points worth pinning are: the ``state_preference`` Literal is
wired off :data:`US_STATES`, ``WirePayload``'s extra-forbid covers
``owner_id`` (server-controlled, must not be accepted on the wire),
and ``PartialUpdate``'s at-least-one-field rule is in effect.
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from src.domain.logic.programs.schema import (
    ProgramCreate,
    ProgramUpdate,
)


def _create_kwargs(**overrides):
    base = dict(org_id=uuid.uuid4(), name="RISE IOP")
    return {**base, **overrides}


def test_create_accepts_minimal():
    org_id = uuid.uuid4()
    payload = ProgramCreate(org_id=org_id, name="RISE IOP")
    assert payload.org_id == org_id
    assert payload.name == "RISE IOP"
    # Defaults populated.
    assert payload.accepting_referrals is True
    assert payload.state_preference is None
    assert payload.description is None


def test_create_strips_name():
    payload = ProgramCreate(org_id=uuid.uuid4(), name="  RISE IOP  ")
    assert payload.name == "RISE IOP"


def test_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        ProgramCreate(org_id=uuid.uuid4(), name="   ")


def test_create_accepts_us_state_preference():
    payload = ProgramCreate(**_create_kwargs(state_preference="CA"))
    assert payload.state_preference == "CA"


def test_create_rejects_unknown_state_preference():
    with pytest.raises(ValidationError):
        ProgramCreate(**_create_kwargs(state_preference="ZZ"))


def test_create_accepts_dates():
    payload = ProgramCreate(
        **_create_kwargs(start_date=date(2026, 5, 1), end_date=date(2026, 8, 1))
    )
    assert payload.start_date == date(2026, 5, 1)
    assert payload.end_date == date(2026, 8, 1)


def test_create_rejects_owner_id_on_wire():
    """``owner_id`` is server-derived from the requesting user — accepting
    it on the wire would let a client impersonate a different owner."""
    with pytest.raises(ValidationError):
        ProgramCreate(**_create_kwargs(owner_id=uuid.uuid4()))


def test_update_at_least_one_field_required():
    with pytest.raises(ValidationError):
        ProgramUpdate()


def test_update_accepts_single_field():
    payload = ProgramUpdate(name="Renamed")
    assert payload.name == "Renamed"


def test_update_org_id_accepted():
    new_org = uuid.uuid4()
    payload = ProgramUpdate(org_id=new_org)
    assert payload.org_id == new_org


def test_update_rejects_unknown_state_preference():
    with pytest.raises(ValidationError):
        ProgramUpdate(state_preference="ZZ")


# --- Steady-state context (website / referral instructions) -------------


def test_create_defaults_free_text_to_none():
    """Free-text fields default to ``None``."""
    payload = ProgramCreate(**_create_kwargs())
    assert payload.website is None
    assert payload.referral_instructions is None


def test_create_accepts_free_text_context():
    payload = ProgramCreate(
        **_create_kwargs(
            website="https://example.com",
            referral_instructions="Email intake@example.com.",
        )
    )
    assert payload.website == "https://example.com"
    assert payload.referral_instructions == "Email intake@example.com."


def test_create_strips_blank_website_to_none():
    """`StrippedOptionalText` collapses empty/whitespace-only input to
    ``None`` — HTML forms post blank `<input>` as ``''``."""
    payload = ProgramCreate(**_create_kwargs(website="   "))
    assert payload.website is None


def test_update_accepts_website():
    payload = ProgramUpdate(website="https://example.com")
    assert payload.website == "https://example.com"


# --- Languages (#1358 PR-f, parent-schema extension) --------------------


def test_create_defaults_languages_to_english():
    """`languages` defaults to `["en"]`, matching the column's
    server-side default and the prior `OpeningDetail` default."""
    payload = ProgramCreate(**_create_kwargs())
    assert payload.languages == ["en"]


def test_create_accepts_explicit_languages():
    payload = ProgramCreate(**_create_kwargs(languages=["en", "es"]))
    assert payload.languages == ["en", "es"]


def test_create_normalizes_scalar_language_to_list():
    payload = ProgramCreate(**_create_kwargs(languages="es"))
    assert payload.languages == ["es"]


def test_create_rejects_unknown_language():
    with pytest.raises(ValidationError):
        ProgramCreate(**_create_kwargs(languages=["not_a_real_language"]))


def test_update_accepts_languages_patch():
    payload = ProgramUpdate(languages=["en", "es"])
    assert payload.languages == ["en", "es"]


def test_update_accepts_empty_languages_to_clear():
    """`[]` clears the language list; `None` (omitted) leaves unchanged."""
    payload = ProgramUpdate(languages=[])
    assert payload.languages == []


def test_update_rejects_unknown_language():
    with pytest.raises(ValidationError):
        ProgramUpdate(languages=["not_a_real_language"])


def test_read_defaults_languages_to_english():
    """A Program row with no explicit `languages` reads as `["en"]`."""
    from datetime import datetime, timezone

    from src.domain.logic.programs.schema import ProgramRead

    now = datetime.now(timezone.utc)
    p = ProgramRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "org_id": uuid.uuid4(),
            "org_name": "Sunrise",
            "name": "RISE IOP",
            "accepting_referrals": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert p.languages == ["en"]
