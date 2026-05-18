"""Tests for the `WirePayload`, `ReadProjection`, and `PartialUpdate` bases.

Each base's behavior on a concrete entity schema is covered by the
per-cluster test files (`schemas/providers/test_provider.py`,
`schemas/posts/test_post.py`). These tests pin the bases themselves so
a regression that broke every concrete schema at once would be caught
here, where the cause lives.
"""

import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest
from pydantic import ValidationError

from src.framework.schema_validators import (
    OptionalUuid,
    PartialUpdate,
    ReadProjection,
    WirePayload,
)


class _AWirePayload(WirePayload):
    a: int


class _AReadProjection(ReadProjection):
    a: int


class _AnUpdate(PartialUpdate):
    a: int | None = None
    b: int | None = None


class _DiscriminatedUpdate(PartialUpdate):
    at_least_one_field_exclude: ClassVar[frozenset[str]] = frozenset({"kind"})

    kind: str
    a: int | None = None


def test_wire_payload_rejects_unknown_field():
    """`extra="forbid"` — unknown fields 422 instead of being dropped."""
    with pytest.raises(ValidationError):
        _AWirePayload(a=1, unknown="value")


def test_wire_payload_accepts_known_field():
    assert _AWirePayload(a=1).a == 1


def test_read_projection_validates_from_orm_like_object():
    """`from_attributes=True` — read attributes off any attr-bag."""
    obj = SimpleNamespace(a=42)
    instance = _AReadProjection.model_validate(obj)
    assert instance.a == 42


def test_partial_update_rejects_empty_patch():
    with pytest.raises(ValidationError) as exc:
        _AnUpdate()
    assert "at least one editable field" in str(exc.value)


def test_partial_update_accepts_single_field():
    instance = _AnUpdate(a=1)
    assert instance.a == 1
    assert instance.b is None


def test_partial_update_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _AnUpdate(unknown=1)


def test_partial_update_discriminator_excluded_from_rule():
    # Only `kind` set → still rejected because the discriminator
    # doesn't count toward "at least one editable field."
    with pytest.raises(ValidationError) as exc:
        _DiscriminatedUpdate(kind="x")
    assert "at least one editable field" in str(exc.value)


def test_partial_update_discriminator_plus_one_field_accepts():
    instance = _DiscriminatedUpdate(kind="x", a=1)
    assert instance.kind == "x"
    assert instance.a == 1


# --- OptionalUuid ------------------------------------------------------
#
# `OptionalUuid` exists because HTML forms can't omit a field — a blank
# `<input>` posts as `""`, which plain `UUID | None` rejects before the
# `None` arm is even considered. The regression we're pinning is the
# prod 422 from POST /organizations with `parent_org_id=` (#issue).


class _OptionalUuidPayload(WirePayload):
    fk: OptionalUuid = None


def test_optional_uuid_coerces_empty_string_to_none():
    """The headline bug: an HTML form's blank input MUST become `None`,
    not a 422."""
    assert _OptionalUuidPayload(fk="").fk is None


def test_optional_uuid_coerces_whitespace_only_to_none():
    assert _OptionalUuidPayload(fk="   ").fk is None


def test_optional_uuid_accepts_real_uuid_string():
    value = uuid.uuid4()
    assert _OptionalUuidPayload(fk=str(value)).fk == value


def test_optional_uuid_accepts_uuid_object():
    value = uuid.uuid4()
    assert _OptionalUuidPayload(fk=value).fk == value


def test_optional_uuid_accepts_none():
    assert _OptionalUuidPayload(fk=None).fk is None


def test_optional_uuid_rejects_malformed_uuid():
    """Coercion is `"" -> None` only — actual garbage still 422s."""
    with pytest.raises(ValidationError):
        _OptionalUuidPayload(fk="not-a-uuid")
