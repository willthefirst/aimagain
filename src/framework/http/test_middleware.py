"""Tests for `src/framework/http/middleware.py`."""

from .middleware import _strip_empty_pairs


def test_strip_empty_value():
    assert _strip_empty_pairs(b"x=") == b""


def test_strip_keeps_non_empty():
    assert _strip_empty_pairs(b"x=1") == b"x=1"


def test_strip_mixed_keeps_only_non_empty():
    assert _strip_empty_pairs(b"a=&b=2&c=") == b"b=2"


def test_strip_keeps_whitespace_value():
    """`%20` is an encoded space — a real value, not empty."""
    assert _strip_empty_pairs(b"x=%20") == b"x=%20"


def test_strip_flag_style_no_equals():
    """`?key` with no `=` has no value; treat as absent."""
    assert _strip_empty_pairs(b"flag") == b""


def test_strip_keeps_value_containing_equals():
    """`x=a=b` has value `a=b`; only the FIRST `=` separates name and value."""
    assert _strip_empty_pairs(b"x=a=b") == b"x=a=b"


def test_strip_collapses_repeated_ampersands():
    assert _strip_empty_pairs(b"a=1&&b=2") == b"a=1&b=2"


def test_strip_repeated_key_keeps_non_empty_instances():
    assert _strip_empty_pairs(b"x=a&x=&x=b") == b"x=a&x=b"


def test_strip_empty_input_returns_empty():
    assert _strip_empty_pairs(b"") == b""
