"""Cross-module schema validator primitives.

Home for `Annotated[T, AfterValidator(fn)]` aliases and small helpers
that are used by 2+ schema modules. Keeping them here means a domain
schema module never has to import primitives from a peer domain module
(e.g. `provider_profile.py` reaching into `post.py`).

Trigger to add something here: a primitive is used by 2+ schema modules
(rule of three, applied generously when callers would otherwise import
across a domain boundary), or two modules are about to define
near-duplicates of the same helper.

Do **not** add: domain-specific Annotated aliases that reference one
domain's vocabularies, base classes that bake in domain shape, or
anything used by exactly one schema module today.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel

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
ZipText = Annotated[str, AfterValidator(_validate_zip)]
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
