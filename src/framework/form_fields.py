"""Schema-driven form-field rendering.

`field_spec(schema_cls, name)` introspects a Pydantic schema's
`FieldInfo` and returns a normalized dict the `field_for` Jinja macro
(in `src/domain/templates/_shared/form_fields.html`) dispatches on. The point
is to derive the form's HTML attributes from the same Pydantic field
that validates the request — adding a `Literal[*US_STATES]` to the
schema flows automatically to the form's `<select>`; tightening
`ZipText`'s pattern updates the form's `pattern` attribute.

What's derived today:

  - `required` — from whether the field's annotation is `T | None`.
  - `kind="select"` + `choices` + (optional) `labels` — for
    `Literal[*TUPLE]` fields. Labels are resolved by tuple-value
    lookup against `register_choice_labels()` calls (see
    `src/framework/templating.py`).
  - `pattern` / `maxlength` — from any `HtmlPattern` marker attached to
    an `Annotated[...]` alias in `src/framework/schema_validators.py`. The
    schema's regex validator stays the source of truth; the marker
    just exposes a *form* rendering of the same constraint.
  - Default `kind="text"` for everything else.

What's deliberately NOT derived (yet):

  - Field labels — the human label ("Practice name") is passed at the
    call site. Keeps copy under template-author control.
  - Multi-select / checkbox-grid / radio-bool — these have form-level
    grouping (fieldset/legend) that the existing macros own; they
    should be added once their schema-side shape (e.g. `list[Literal]`
    + a discriminator metadata marker) is settled.
  - `select_field` placeholder behavior — `field_for` always passes
    `placeholder=true`, which suits create forms. Edit forms with
    pre-filled `current` already suppress the placeholder inside
    `select_field`.
"""

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


# Choice-tuple → label-dict registry, populated at startup by
# `register_choice_labels()` from `src/framework/templating.py`. Lookup is
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
    for marker in field.metadata:
        if isinstance(marker, HtmlPattern):
            if marker.pattern is not None:
                pattern = marker.pattern
            if marker.maxlength is not None:
                maxlength = marker.maxlength

    return {
        "kind": "text",
        "name": name,
        "required": not optional,
        "pattern": pattern,
        "maxlength": maxlength,
    }
