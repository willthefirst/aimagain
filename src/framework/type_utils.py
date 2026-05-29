"""Python type annotation helpers for Optional / Union introspection.

Used wherever framework code needs to detect `T | None` and peel off the
`None` arm at import time (form-field rendering, route-synthesis). Having
one implementation avoids the two copies that existed in
`rendering/form_fields.py` and `dispatch/mounts/_synth.py`.
"""

from types import UnionType
from typing import Any, Union, get_args, get_origin


def is_optional(annotation: Any) -> bool:
    """True if *annotation* is ``T | None`` — either PEP 604 or ``Optional[T]``."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return type(None) in get_args(annotation)
    return False


def strip_optional(annotation: Any) -> Any:
    """Return the non-``None`` arm of ``T | None``.

    For multi-arm unions (``A | B | None``), returns the union of the
    non-``None`` arms (``A | B``). Callers should only call this after
    confirming ``is_optional`` is ``True``; the behaviour on a
    non-optional annotation is undefined.
    """
    args = tuple(a for a in get_args(annotation) if a is not type(None))
    if len(args) == 1:
        return args[0]
    return Union[args]  # type: ignore[return-value]
