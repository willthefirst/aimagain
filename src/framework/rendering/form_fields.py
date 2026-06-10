"""Schema-driven form-field rendering: Pydantic FieldInfo → dict for the `field_for` Jinja macro."""

from dataclasses import dataclass
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from src.framework.type_utils import is_optional, strip_optional


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


@dataclass(frozen=True)
class HtmlUrl:
    """Annotation marker that swaps `field_for`'s default `<input
    type=text>` rendering for `<input type=url>` on a string field.
    Browsers gate submission on URL syntax, switch mobile keyboards to
    a URL layout, and surface autofill differently. Same no-payload
    shape as `HtmlTextarea` — presence on the `Annotated[...]` metadata
    is the signal.
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


def _resolve_field(schema_cls: type[BaseModel], name: str) -> tuple[Any, bool]:
    """Look up a field by name on a Pydantic schema. Returns
    ``(FieldInfo, parent_optional)``.

    Direct match wins. If ``name`` isn't a top-level field but contains
    an underscore, try to interpret it as ``<parent>_<sub>`` where
    ``parent`` is a top-level field whose annotation is a nested
    :class:`BaseModel` (or ``BaseModel | None`` for partial-update
    variants). This is how flat form field names like ``location_city``
    resolve into the embedded ``location: Location`` value object on
    the clinician / client-referral schemas — the form template
    keeps passing ``field_for(schema, 'location_city', ...)`` and we
    silently route into the sub-model.

    ``parent_optional`` is the optional-ness of the parent field (the
    embedding ``location`` field on the update variants is
    ``LocationPartial | None``); the caller composes it with the
    sub-field's own optional-ness so a required sub-field on an
    optional parent renders as optional.
    """
    fields = schema_cls.model_fields
    if name in fields:
        return fields[name], False
    if "_" not in name:
        raise KeyError(name)
    parent_name, _, sub_name = name.partition("_")
    while parent_name:
        if parent_name in fields:
            parent_field = fields[parent_name]
            parent_anno = parent_field.annotation
            parent_optional = is_optional(parent_anno)
            inner_parent = (
                strip_optional(parent_anno) if parent_optional else parent_anno
            )
            if isinstance(inner_parent, type) and issubclass(inner_parent, BaseModel):
                if sub_name in inner_parent.model_fields:
                    return inner_parent.model_fields[sub_name], parent_optional
            break
        # Fall back to trying longer prefixes (e.g. a field literally
        # named ``foo_bar`` shadows a nested ``foo.bar`` lookup). Walk
        # right one underscore at a time.
        idx = sub_name.find("_")
        if idx == -1:
            break
        parent_name = f"{parent_name}_{sub_name[:idx]}"
        sub_name = sub_name[idx + 1 :]
    raise KeyError(name)


def field_spec(schema_cls: type[BaseModel], name: str) -> dict[str, Any]:
    """Return the rendering spec for `schema_cls.<name>`. See module
    docstring for what's derived.

    ``name`` may be a flat path like ``location_city`` that resolves
    through a top-level field whose annotation is a nested
    :class:`BaseModel` (see :func:`_resolve_field`). The rendered
    ``<input name=...>`` keeps the flat ``name`` — the schema's
    ``model_validator(mode="before")`` re-nests it before validation,
    so the wire/HTML contract stays the same as before #451.
    """
    field, parent_optional = _resolve_field(schema_cls, name)
    annotation = field.annotation
    optional = parent_optional or is_optional(annotation)
    inner = strip_optional(annotation) if is_optional(annotation) else annotation

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
    is_url = False
    # Pydantic only surfaces `Annotated[T, M1, M2]` metadata on
    # `FieldInfo.metadata` when the field annotation is the bare
    # Annotated form. Once you wrap it in `Optional[...]` (e.g.
    # `ZipText | None` on `LocationPartial`), the inner Annotated's
    # markers stop appearing on FieldInfo.metadata. Walk the inner
    # annotation's `__metadata__` too so the form-rendering markers
    # (`HtmlPattern`, `HtmlTextarea`, `HtmlUrl`) carry through to
    # optional partial-update fields the same way they do for
    # required Create fields.
    inner_metadata = tuple(getattr(inner, "__metadata__", ()) or ())
    for marker in tuple(field.metadata) + inner_metadata:
        if isinstance(marker, HtmlPattern):
            if marker.pattern is not None:
                pattern = marker.pattern
            if marker.maxlength is not None:
                maxlength = marker.maxlength
        elif isinstance(marker, HtmlTextarea):
            is_textarea = True
        elif isinstance(marker, HtmlUrl):
            is_url = True

    if is_textarea:
        return {
            "kind": "textarea",
            "name": name,
            "required": not optional,
        }

    if is_url:
        return {
            "kind": "url",
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
