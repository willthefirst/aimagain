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
from typing import Annotated, ClassVar

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


# --- At-least-one-field rule --------------------------------------------


def assert_any_field_set(
    model: BaseModel, *, exclude: frozenset[str] = frozenset()
) -> None:
    """Raise `ValueError` if every field on `model` (excluding any name in
    `exclude`) is `None`. Shared between every partial-update variant so
    the rule lives in one place. Pass `exclude={"kind"}` (or similar) for
    discriminated-union Updates where the discriminator is always
    required and shouldn't count toward "at least one editable field"."""
    fields = type(model).model_fields
    if all(getattr(model, name) is None for name in fields if name not in exclude):
        raise ValueError("at least one editable field must be provided")


class WirePayload(BaseModel):
    """Base for Create / state-axis-body wire schemas.

    Carries ``ConfigDict(extra="forbid")`` so unknown fields 422 instead
    of being silently dropped. PATCH/Update variants inherit
    :class:`PartialUpdate` instead — it owns the same config plus the
    at-least-one-field rule.
    """

    model_config = ConfigDict(extra="forbid")


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
