"""Cross-module schema validator primitives.

Home for `Annotated[T, AfterValidator(fn)]` aliases and small helpers
that are used by 2+ schema modules. Keeping them here means a domain
schema module never has to import primitives from a peer domain module
(e.g. `provider.py` reaching into `post.py`).

Trigger to add something here: a primitive is used by 2+ schema modules
(rule of three, applied generously when callers would otherwise import
across a domain boundary), or two modules are about to define
near-duplicates of the same helper.

Do **not** add: domain-specific Annotated aliases that reference one
domain's vocabularies, base classes that bake in domain shape, or
anything used by exactly one schema module today.
"""

import re
import types
from typing import Annotated, ClassVar, Literal, Union, get_args, get_origin

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator

from src.framework.rendering.form_fields import HtmlPattern

# --- Field-cleaning helpers ---------------------------------------------
#
# Each runs AFTER Pydantic's type validation, so for required fields
# typed as plain `str` Pydantic has already rejected `None` before the
# validator sees the value. For Update fields typed as `T | None`,
# Pydantic skips AfterValidator on the `None` arm, so the helper only
# ever sees real strings. That's why a single helper works for both
# Create (required) and Update (optional) — no `_or_none` variants
# needed.

_ZIP_RE = re.compile(r"^\d{5}$")


def _strip_required(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


def _validate_zip(v: str) -> str:
    v = v.strip()
    if not _ZIP_RE.match(v):
        raise ValueError("must be a 5-digit ZIP code")
    return v


def _strip_optional(v: str | None) -> str | None:
    """Strip whitespace; collapse empty/whitespace-only to `None`. Used
    for optional free-text fields where '' from a blank input means
    absent. Receives `None` directly because the surrounding type is
    `str | None` (not `str`), so the AfterValidator fires on every
    arm of the union — including `None`."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def scalar_to_list(v):
    """Wrap a single string in a one-element list.

    HTML form posts collapse a 1-checkbox-checked group to a scalar
    (htmx's `json-enc` only emits an array when the same name appears
    2+ times); this `BeforeValidator` normalizes that 1-element case
    before the `Literal[*TUPLE]` member check fires. The 0-element
    case is handled by the field default `[]`; the 2+ case already
    arrives as a list.

    Used by every multi-checkbox field across domain schemas
    (posts, providers, affiliations, ...). Each schema layers its own
    `Literal[*TUPLE]` over the shared coercion:

        MyField = Annotated[
            list[Literal[*MY_TUPLE]],
            BeforeValidator(scalar_to_list),
        ]
    """
    if isinstance(v, str):
        return [v]
    return v


# --- Annotated field types ----------------------------------------------
#
# Attach the cleaning rule to the field's type, not to a per-class
# `@field_validator` method. Each variant just declares the field with
# the right alias; the validator definition lives once.

StrippedText = Annotated[str, AfterValidator(_strip_required)]
# `HtmlPattern` mirrors the regex enforced by `_validate_zip` so the
# form's `<input pattern>` rejects bad ZIPs client-side. The validator
# stays the source of truth — keep the two regexes aligned at this
# definition site.
ZipText = Annotated[
    str, AfterValidator(_validate_zip), HtmlPattern(pattern=r"\d{5}", maxlength=5)
]
StrippedOptionalText = Annotated[str | None, AfterValidator(_strip_optional)]


# --- Empty-string-to-None coercion on nullable scalars ------------------


def _peel_annotated(annotation):
    """Annotated[X, ...] → X; pass through otherwise."""
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _is_blank_coercible_field(annotation) -> bool:
    """True if `annotation` is `T | None` where ``T`` is a scalar that
    can't honestly hold the empty string — UUID, date, int, float,
    bool, Decimal, Literal, etc.

    HTML forms can't omit a field — a blank ``<input>`` posts ``""``.
    Pydantic's union resolution tries ``T`` first and 422s when ``""``
    isn't a valid ``T``, never getting to the ``None`` arm. The
    only correct interpretation of a blank input on a nullable
    non-string scalar is ``None``, so coerce at the model layer
    *before* per-field validation runs.

    Skip ``str | None`` — empty string is itself a valid ``str``, and
    blank-collapsing is opt-in via ``StrippedOptionalText`` where the
    domain wants it.

    Skip container types (``list``/``set``/``tuple``/``dict``) and
    ``BaseModel`` subclasses — those never receive a bare empty
    string from a form (their inputs are arrays or dicts), so the
    coercion is a no-op anyway; declaring it as a no-op keeps the
    detector honest rather than relying on the runtime value-shape
    check downstream.
    """
    annotation = _peel_annotated(annotation)
    origin = get_origin(annotation)
    if origin not in (Union, types.UnionType):
        return False
    args = get_args(annotation)
    non_none = [a for a in args if a is not type(None)]
    if len(args) != 2 or len(non_none) != 1:
        return False
    inner = _peel_annotated(non_none[0])
    if inner is str:
        return False
    inner_origin = get_origin(inner)
    if inner_origin is Literal:
        return True
    if inner_origin in (list, set, tuple, dict, frozenset):
        return False
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return False
    return True


# --- At-least-one-field rule --------------------------------------------


def _field_is_set(value) -> bool:
    """Decide whether a field's value counts as "set" for the
    at-least-one-field rule.

    Non-``None`` values count. A nested :class:`BaseModel` value (the
    typical case is :class:`~src.domain.logic.value_objects.location.LocationPartial`
    on the provider / client-referral Update variants — #451) counts
    only if at least one of *its* own fields is set; an all-``None``
    partial value-object is treated as the no-op patch ``None`` it
    semantically represents, so a PATCH that only sets
    ``location_city: None`` (which flattens to a
    ``LocationPartial(city=None)``) still fails the rule.
    """
    if value is None:
        return False
    if isinstance(value, BaseModel):
        nested_fields = type(value).model_fields
        return any(_field_is_set(getattr(value, name)) for name in nested_fields)
    return True


def assert_any_field_set(
    model: BaseModel, *, exclude: frozenset[str] = frozenset()
) -> None:
    """Raise `ValueError` if every field on `model` (excluding any name in
    `exclude`) is unset. Shared between every partial-update variant so
    the rule lives in one place. Pass `exclude={"kind"}` (or similar) for
    discriminated-union Updates where the discriminator is always
    required and shouldn't count toward "at least one editable field".

    "Unset" means ``None`` for scalar fields, and "every subfield
    unset" for nested :class:`BaseModel` fields — see
    :func:`_field_is_set` for the recursive rule.
    """
    fields = type(model).model_fields
    if not any(
        _field_is_set(getattr(model, name)) for name in fields if name not in exclude
    ):
        raise ValueError("at least one editable field must be provided")


class WirePayload(BaseModel):
    """Base for Create / state-axis-body wire schemas.

    Carries ``ConfigDict(extra="forbid")`` so unknown fields 422 instead
    of being silently dropped. PATCH/Update variants inherit
    :class:`PartialUpdate` instead — it owns the same config plus the
    at-least-one-field rule.

    Every nullable non-string scalar field on a subclass automatically
    gets the empty-string→None coercion documented on
    :func:`_is_blank_coercible_field`. The rule applies once at this
    layer so individual schemas don't reach for per-field
    ``BeforeValidator`` aliases — the same way ``extra="forbid"`` is
    declared once here rather than on each schema's ``model_config``.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_blank_strings_on_nullable_scalars(cls, data):
        if not isinstance(data, dict):
            return data
        for name, field in cls.model_fields.items():
            if name not in data:
                continue
            value = data[name]
            if not isinstance(value, str) or value.strip() != "":
                continue
            if _is_blank_coercible_field(field.annotation):
                data[name] = None
        return data


class ReadProjection(BaseModel):
    """Base for Read / AuditSnapshot variants.

    Carries ``ConfigDict(from_attributes=True)`` so
    ``schema.model_validate(orm_obj)`` reads attributes off SQLAlchemy
    rows (and any other attr-bag) without each schema redeclaring the
    knob.
    """

    model_config = ConfigDict(from_attributes=True)


class PartialUpdate(WirePayload):
    """Base class for PATCH/Update wire schemas.

    Extends :class:`WirePayload` (so ``extra="forbid"`` carries through)
    with a post-validation hook that calls
    ``assert_any_field_set(self, exclude=cls.at_least_one_field_exclude)``
    so a PATCH with every field absent rejects with a clear message.

    Discriminated-union Updates (posts) override ``at_least_one_field_exclude``
    to ``frozenset({"kind"})`` so the always-present discriminator
    doesn't count toward "at least one editable field." Non-discriminated
    Updates leave the default empty set.
    """

    # `ClassVar` so pydantic treats this as a class-level configuration
    # knob, not a model field. Discriminated-union Updates (posts) set
    # it to `frozenset({"kind"})`; non-discriminated ones inherit the
    # empty default.
    at_least_one_field_exclude: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _assert_any_field_set(self) -> "PartialUpdate":
        assert_any_field_set(self, exclude=type(self).at_least_one_field_exclude)
        return self
