"""Tests for the `PartialUpdate` base class.

The validator's behavior on each concrete entity Update schema is
covered by the per-cluster test files (`schemas/providers/test_provider.py`,
`schemas/posts/test_post.py`). These tests pin the base class itself
so a regression that broke every concrete Update at once would be
caught here, where the cause lives.
"""

from typing import ClassVar

import pytest
from pydantic import ValidationError

from src.schemas._validators import PartialUpdate


class _AnUpdate(PartialUpdate):
    a: int | None = None
    b: int | None = None


class _DiscriminatedUpdate(PartialUpdate):
    at_least_one_field_exclude: ClassVar[frozenset[str]] = frozenset({"kind"})

    kind: str
    a: int | None = None


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
