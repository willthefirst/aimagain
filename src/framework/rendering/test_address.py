"""Tests for `src/framework/rendering/address.py`."""

from src.framework.rendering.address import full_address


def test_full_address_with_all_parts():
    assert full_address("San Francisco", "CA", "94110") == "San Francisco, CA 94110"


def test_full_address_with_no_parts_returns_none():
    assert full_address(None, None, None) is None
    assert full_address("", "", "") is None


def test_full_address_city_only():
    assert full_address("San Francisco", None, None) == "San Francisco"


def test_full_address_state_only():
    assert full_address(None, "CA", None) == "CA"


def test_full_address_zip_only():
    assert full_address(None, None, "94110") == "94110"


def test_full_address_city_and_state_no_zip():
    assert full_address("San Francisco", "CA", None) == "San Francisco, CA"


def test_full_address_city_and_zip_no_state():
    """City + ZIP joins with a single space (no leading comma)."""
    assert full_address("San Francisco", None, "94110") == "San Francisco 94110"


def test_full_address_state_and_zip_no_city():
    assert full_address(None, "CA", "94110") == "CA 94110"


def test_full_address_empty_string_treated_as_missing():
    """Empty strings count as absent — `any(("", "", ""))` is falsey."""
    assert full_address("", "CA", "94110") == "CA 94110"
