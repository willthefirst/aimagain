"""Schema-driven form-field rendering: Pydantic FieldInfo → dict for the `field_for` Jinja macro."""

from dataclasses import dataclass
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel


@dataclass(frozen=True)
class HtmlPattern:
    """Annotation marker carrying HTML pattern/maxlength hints for an
    `Annotated[...]` alias in `src/framework/schema_validators.py`.

    The schema's validator is the authoritative constraint; this marker
    exposes a form-side rendering of the same constraint so the
    `<input>` rejects bad values client-side too. Define the regex once
    on the alias and reuse it via `Annotated[..., HtmlPattern(pattern,
    maxlength)]` — the alias is the one place both surfaces look.
    """

    pattern: str | None = None
    maxlength: int | None = None


@dataclass(frozen=True)
class HtmlTextarea:
    """Annotation marker that swaps `field_for`'s default `<input
    type=text>` rendering for `<textarea>` on a string field. Free-text
    fields long enough to want a multi-line control (descriptions,
    instructions) reach for this; everything else stays text by default.
    No payload — presence on the field's `Annotated[...]` metadata is
    the signal.
    """


# Choice-tuple → label-dict registry, populated at startup by
# `register_choice_labels()` from `src/framework/rendering/templating.py`. Lookup is
# by tuple value (not identity) because `Literal[*TUPLE]` unpacks the
# source tuple into a fresh tuple inside `typing.Literal`'s args.
_CHOICE_LABELS: dict[tuple, dict[str, str] | None] = {}


def register_choice_labels(
    choices: tuple[str, ...], labels: dict[str, str] | None
) -> None:
    """Register the labels dict (or `None`) for a controlled-vocabulary
    tuple, so `field_spec` can resolve labels for any
    `Literal[*tuple]` it sees. Idempotent — re-registering the same
    tuple with the same labels is a no-op."""
    _CHOICE_LABELS[tuple(choices)] = labels


def _is_optional(annotation: Any) -> bool:
    """`True` if `annotation` is `T | None` (either the PEP 604 union
    or `typing.Union[T, None]`)."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return type(None) in get_args(annotation)
    return False


def _strip_optional(annotation: Any) -> Any:
    """Return the non-None arm of a `T | None` annotation. If
    `annotation` is a multi-arm union (`A | B | None`), returns the
    union of the non-None arms."""
    args = tuple(a for a in get_args(annotation) if a is not type(None))
    if len(args) == 1:
        return args[0]
    return Union[args]  # type: ignore[return-value]


def field_spec(schema_cls: type[BaseModel], name: str) -> dict[str, Any]:
    """Return the rendering spec for `schema_cls.<name>`. See module
    docstring for what's derived."""
    field = schema_cls.model_fields[name]
    annotation = field.annotation
    optional = _is_optional(annotation)
    inner = _strip_optional(annotation) if optional else annotation

    # `list[Literal[*T]]` (with or without `| None`) is unambiguous —
    # it IS a multi-select. No marker needed to disambiguate, unlike
    # the `str` vs `str-as-textarea` case (`HtmlTextarea`).
    if get_origin(inner) is list:
        list_args = get_args(inner)
        if len(list_args) == 1 and get_origin(list_args[0]) is Literal:
            choices = list(get_args(list_args[0]))
            labels = _CHOICE_LABELS.get(tuple(choices))
            return {
                "kind": "multi_select",
                "name": name,
                "required": not optional,
                "choices": choices,
                "labels": labels,
            }

    if get_origin(inner) is Literal:
        choices = list(get_args(inner))
        labels = _CHOICE_LABELS.get(tuple(choices))
        return {
            "kind": "select",
            "name": name,
            "required": not optional,
            "choices": choices,
            "labels": labels,
        }

    pattern: str | None = None
    maxlength: int | None = None
    is_textarea = False
    for marker in field.metadata:
        if isinstance(marker, HtmlPattern):
            if marker.pattern is not None:
                pattern = marker.pattern
            if marker.maxlength is not None:
                maxlength = marker.maxlength
        elif isinstance(marker, HtmlTextarea):
            is_textarea = True

    if is_textarea:
        return {
            "kind": "textarea",
            "name": name,
            "required": not optional,
        }

    return {
        "kind": "text",
        "name": name,
        "required": not optional,
        "pattern": pattern,
        "maxlength": maxlength,
    }
