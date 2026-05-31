"""Tests for ``parse_form_to_payload``.

The parser is the boundary between FastAPI's form parser and the
Pydantic-validated payload dict. Two contracts live here:

1. Single value → scalar; repeated key → list (the multi-select
   contract that ``multi_select_field`` depends on).
2. Repeated key whose values are all ``"true"``/``"false"`` collapses
   to the last value as a scalar (the checkbox+hidden Rails pattern
   that ``checkbox_field`` depends on).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.datastructures import FormData

from src.framework.http.forms import parse_form_to_payload


def _request_with_form(pairs: list[tuple[str, str]]) -> Any:
    """Tiny stand-in for a Starlette ``Request`` whose ``.form()``
    returns a ``FormData`` built from a list of (key, value) pairs.
    The real parser only touches ``request.form()`` so a namespace
    object with the same coroutine suffices."""

    form = FormData(pairs)

    async def _form():
        return form

    return SimpleNamespace(form=_form)


# --- single-value / scalar contract ----------------------------------------


@pytest.mark.asyncio
async def test_single_value_returns_scalar() -> None:
    """One occurrence of a key → scalar string. Pins the "schemas
    typed as ``str | None`` keep working" half of the contract."""
    req = _request_with_form([("name", "Alice")])
    payload = await parse_form_to_payload(req)
    assert payload == {"name": "Alice"}


@pytest.mark.asyncio
async def test_multiple_distinct_values_return_list() -> None:
    """Multi-select fields submit the same name with distinct
    controlled-vocab values; the parser returns a list so Pydantic's
    ``list[str]`` validators see the right shape."""
    req = _request_with_form([("services", "psychiatry"), ("services", "therapy")])
    payload = await parse_form_to_payload(req)
    assert payload == {"services": ["psychiatry", "therapy"]}


# --- checkbox+hidden Rails pattern -----------------------------------------


@pytest.mark.asyncio
async def test_checkbox_hidden_unchecked_collapses_to_false() -> None:
    """``checkbox_field`` emits the hidden ``false`` followed by the
    checkbox itself. Unchecked → only the hidden ships. With one
    value the existing scalar rule applies — payload is the string
    ``"false"`` which Pydantic's ``bool`` validator coerces to
    ``False``."""
    req = _request_with_form([("sliding_scale", "false")])
    payload = await parse_form_to_payload(req)
    assert payload == {"sliding_scale": "false"}


@pytest.mark.asyncio
async def test_checkbox_hidden_checked_last_wins_true() -> None:
    """Checked → both fields ship in document order: hidden ``false``
    then checkbox ``true``. The bool-string-list heuristic collapses
    to the last value (``"true"``), which Pydantic coerces to
    ``True``."""
    req = _request_with_form(
        [("accepts_out_of_network", "false"), ("accepts_out_of_network", "true")]
    )
    payload = await parse_form_to_payload(req)
    assert payload == {"accepts_out_of_network": "true"}


@pytest.mark.asyncio
async def test_bool_collapse_does_not_fire_on_mixed_values() -> None:
    """The heuristic requires ALL values in the list to be
    ``"true"``/``"false"`` strings. A multi-select that legitimately
    includes one of those tokens alongside non-bool values keeps the
    list shape."""
    req = _request_with_form([("features", "true"), ("features", "telehealth")])
    payload = await parse_form_to_payload(req)
    assert payload == {"features": ["true", "telehealth"]}


@pytest.mark.asyncio
async def test_empty_form_returns_empty_dict() -> None:
    """No fields → empty payload. Sanity check for the iteration
    base case so an empty POST doesn't accidentally seed ``None``
    values into the dict."""
    req = _request_with_form([])
    payload = await parse_form_to_payload(req)
    assert payload == {}
