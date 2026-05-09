"""Tests for `src/core/form_fields.py`.

Covers what `field_spec` derives from a Pydantic field — required-ness,
Literal → select, Annotated `HtmlPattern` markers — using a small
in-test schema. The provider/new.html → `field_for` integration is
exercised by the route test in `src/api/routes/test_providers.py`.
"""

from typing import Annotated, Literal

from pydantic import BaseModel

from src.core.form_fields import (
    HtmlPattern,
    field_spec,
    register_choice_labels,
)

_COLORS = ("red", "green", "blue")
_COLOR_LABELS = {"red": "Red", "green": "Green", "blue": "Blue"}
register_choice_labels(_COLORS, _COLOR_LABELS)

_SIZES = ("s", "m", "l")
register_choice_labels(_SIZES, None)

_PatternedString = Annotated[str, HtmlPattern(pattern=r"\d{5}", maxlength=5)]


class _Sample(BaseModel):
    required_text: str
    optional_text: str | None = None
    required_choice: Literal[*_COLORS]
    optional_choice: Literal[*_COLORS] | None = None
    unlabeled_choice: Literal[*_SIZES]
    patterned: _PatternedString


def test_required_text_field():
    spec = field_spec(_Sample, "required_text")
    assert spec == {
        "kind": "text",
        "name": "required_text",
        "required": True,
        "pattern": None,
        "maxlength": None,
    }


def test_optional_text_field_drops_required():
    spec = field_spec(_Sample, "optional_text")
    assert spec["kind"] == "text"
    assert spec["required"] is False


def test_literal_field_renders_as_select_with_labels():
    spec = field_spec(_Sample, "required_choice")
    assert spec["kind"] == "select"
    assert spec["choices"] == list(_COLORS)
    assert spec["labels"] == _COLOR_LABELS
    assert spec["required"] is True


def test_optional_literal_field_is_select_not_required():
    spec = field_spec(_Sample, "optional_choice")
    assert spec["kind"] == "select"
    assert spec["required"] is False
    assert spec["choices"] == list(_COLORS)


def test_unlabeled_choice_returns_none_labels():
    """Tuples registered without a labels dict (e.g. USPS state codes)
    surface `labels=None` so the macro falls back to using the value
    itself as the option text."""
    spec = field_spec(_Sample, "unlabeled_choice")
    assert spec["kind"] == "select"
    assert spec["labels"] is None


def test_html_pattern_marker_propagates():
    spec = field_spec(_Sample, "patterned")
    assert spec["kind"] == "text"
    assert spec["pattern"] == r"\d{5}"
    assert spec["maxlength"] == 5


def test_zip_text_alias_carries_pattern_in_real_schema():
    """End-to-end: the `ZipText` alias in `src/schemas/_validators.py`
    is the production wiring this prototype targets. If someone removes
    the `HtmlPattern` marker on `ZipText`, the form's client-side
    validation silently drops — catch it here."""
    from src.schemas.providers.provider import ProviderCreate

    spec = field_spec(ProviderCreate, "location_zip")
    assert spec["pattern"] == r"\d{5}"
    assert spec["maxlength"] == 5
