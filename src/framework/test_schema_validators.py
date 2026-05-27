"""Tests for the `WirePayload`, `ReadProjection`, and `PartialUpdate` bases.

Each base's behavior on a concrete entity schema is covered by the
per-cluster test files (`schemas/clinicians/test_clinician.py`,
`schemas/posts/test_post.py`). These tests pin the bases themselves so
a regression that broke every concrete schema at once would be caught
here, where the cause lives.
"""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, ClassVar, Literal

import pytest
from pydantic import BaseModel, BeforeValidator, ValidationError

from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
    scalar_to_list,
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


# --- Empty-string → None on nullable non-string scalars ----------------
#
# `WirePayload._coerce_blank_strings_on_nullable_scalars` collapses a
# blank HTML form input (`""` or whitespace-only) to `None` for any
# nullable non-string scalar field. The regression that motivated this
# is the prod 422 from `POST /organizations` with `parent_org_id=`
# (#550), generalized to every scalar type so future schemas inherit
# the fix.


class _NestedSubModel(BaseModel):
    inner: int


class _ScalarsPayload(WirePayload):
    # Nullable non-string scalars — all coerced from "" to None.
    fk_uuid: uuid.UUID | None = None
    when: date | None = None
    score: int | None = None
    rate: float | None = None
    amount: Decimal | None = None
    flag: bool | None = None
    region: Literal["a", "b"] | None = None
    # str | None is NOT coerced — empty string is a valid str.
    free_text: str | None = None
    # `StrippedOptionalText` opts in to whitespace-collapsing on a
    # `str | None` via its inner AfterValidator. The model-level rule
    # leaves this alone (still a str field); the inner validator does
    # the work.
    optional_text: StrippedOptionalText = None
    # Containers and BaseModel subclasses never receive a bare empty
    # string from a form — verify the detector keeps its hands off.
    tags: list[str] | None = None
    nested: _NestedSubModel | None = None
    # Annotated wrapper around a nullable UUID still gets coerced
    # (the model walks `field.annotation` and peels `Annotated`).
    fk_annotated: Annotated[uuid.UUID | None, "marker"] = None


def test_coerces_blank_uuid():
    assert _ScalarsPayload(fk_uuid="").fk_uuid is None


def test_coerces_whitespace_uuid():
    assert _ScalarsPayload(fk_uuid="   ").fk_uuid is None


def test_coerces_blank_date():
    assert _ScalarsPayload(when="").when is None


def test_coerces_blank_int():
    assert _ScalarsPayload(score="").score is None


def test_coerces_blank_float():
    assert _ScalarsPayload(rate="").rate is None


def test_coerces_blank_decimal():
    assert _ScalarsPayload(amount="").amount is None


def test_coerces_blank_bool():
    assert _ScalarsPayload(flag="").flag is None


def test_coerces_blank_literal():
    """Empty string can never match any literal value — coerce to None
    rather than 422."""
    assert _ScalarsPayload(region="").region is None


def test_coerces_blank_annotated_inner_type():
    """`Annotated[T | None, ...]` is detected as `T | None` after peeling."""
    assert _ScalarsPayload(fk_annotated="").fk_annotated is None


def test_does_not_coerce_blank_str():
    """`str | None`: empty string is a valid str — leave alone."""
    assert _ScalarsPayload(free_text="").free_text == ""


def test_does_not_coerce_blank_stripped_optional_text():
    """`StrippedOptionalText`'s inner AfterValidator owns blank-collapsing
    for `str | None` — the model-level rule defers to it. End-to-end the
    field still ends up `None`, but via the field-local path."""
    assert _ScalarsPayload(optional_text="").optional_text is None
    assert _ScalarsPayload(optional_text="   ").optional_text is None


def test_does_not_affect_list_field():
    """Form `<select multiple>` empties send no key or an empty array —
    never a bare `""`. The detector skips containers regardless."""
    instance = _ScalarsPayload(tags=["one"])
    assert instance.tags == ["one"]


def test_does_not_affect_nested_basemodel_field():
    instance = _ScalarsPayload(nested={"inner": 7})
    assert instance.nested == _NestedSubModel(inner=7)


def test_passes_through_real_uuid_string():
    value = uuid.uuid4()
    assert _ScalarsPayload(fk_uuid=str(value)).fk_uuid == value


def test_passes_through_real_date_string():
    assert _ScalarsPayload(when="2026-06-01").when == date(2026, 6, 1)


def test_passes_through_real_literal_value():
    assert _ScalarsPayload(region="a").region == "a"


def test_malformed_uuid_still_422s():
    """Coercion is `"" -> None` only — actual garbage still 422s."""
    with pytest.raises(ValidationError):
        _ScalarsPayload(fk_uuid="not-a-uuid")


def test_required_str_field_with_blank_value_still_validates_normally():
    """A required `str` (not `str | None`) field still receives the
    empty string and the field-level validator does whatever it does —
    the model-level rule never touches str-typed fields."""

    class _RequiredText(WirePayload):
        name: StrippedText

    # `StrippedText` rejects empty strings via its AfterValidator —
    # the model-level rule doesn't pre-empt that.
    with pytest.raises(ValidationError):
        _RequiredText(name="")


def test_coercion_applies_through_partial_update():
    """`PartialUpdate` inherits from `WirePayload`, so Update schemas
    get the same coercion for free."""

    class _Update(PartialUpdate):
        fk: uuid.UUID | None = None
        name: str | None = None

    # Blank UUID coerces to None; blank str stays as ""; the
    # at-least-one-field rule then sees the str as set.
    instance = _Update(fk="", name="")
    assert instance.fk is None
    assert instance.name == ""


def test_scalar_to_list_wraps_lone_string_in_list():
    """An HTML form with one checkbox checked posts a scalar; the
    coercion lifts it to a one-element list before `Literal` member
    validation runs."""

    class _Checkboxes(WirePayload):
        choices: Annotated[
            list[Literal["a", "b", "c"]], BeforeValidator(scalar_to_list)
        ] = []

    assert _Checkboxes(choices="a").choices == ["a"]


def test_scalar_to_list_passes_lists_through_unchanged():
    """2+ checkboxes arrive as a list already; the coercion is a no-op."""

    class _Checkboxes(WirePayload):
        choices: Annotated[
            list[Literal["a", "b", "c"]], BeforeValidator(scalar_to_list)
        ] = []

    assert _Checkboxes(choices=["a", "b"]).choices == ["a", "b"]


def test_scalar_to_list_rejects_invalid_member_after_lifting():
    """Coercion runs before the `Literal[...]` member check, so an
    invalid scalar still 422s — the helper doesn't bypass validation,
    it just normalizes the wire shape."""

    class _Checkboxes(WirePayload):
        choices: Annotated[
            list[Literal["a", "b", "c"]], BeforeValidator(scalar_to_list)
        ] = []

    with pytest.raises(ValidationError):
        _Checkboxes(choices="z")
