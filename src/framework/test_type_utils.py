"""Pins the contract for `src/framework/type_utils`.

Both `rendering/form_fields.py` and `dispatch/mounts/_synth.py` rely on
these helpers for Optional detection and stripping. Tests here lock in the
expected behaviour for every case both callers exercise.
"""

from typing import Optional, Union

import pytest

from src.framework.type_utils import is_optional, strip_optional


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (str, False),
        (int, False),
        (str | None, True),
        (int | None, True),
        (Optional[str], True),
        (Union[str, None], True),
        (Union[str, int], False),
        (Union[str, int, None], True),
        (list[str], False),
    ],
)
def test_is_optional(annotation, expected):
    assert is_optional(annotation) is expected


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (str | None, str),
        (int | None, int),
        (Optional[str], str),
        (Union[str, None], str),
    ],
)
def test_strip_optional_single_arm(annotation, expected):
    assert strip_optional(annotation) is expected


def test_strip_optional_multi_arm():
    result = strip_optional(Union[str, int, None])
    # The stripped result must contain exactly str and int (no None).
    args = set(result.__args__) if hasattr(result, "__args__") else {result}
    assert args == {str, int}
