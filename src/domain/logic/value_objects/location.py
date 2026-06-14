"""``Location`` wire value object: ``(city, state, zip)`` as a named triple.

The DRY-at-the-Pydantic-layer counterpart to
:class:`src.framework.persistence.mixins.LocationMixin`. Clinician and
client-referral wire schemas embed ``location: Location`` (required-state
flavor) on Create/Read variants and ``location: LocationPartial`` on
Update variants; helpers on those schemas keep the wire/JSON/audit
projection flat (``location_city`` / ``location_state`` / ``location_zip``
at the top level) so existing consumers stay untouched.

Two flavors live here because the schemas have two needs:

- :class:`Location` — Create/Read shape: ``city`` is :class:`StrippedText`
  (required), ``state`` is required ``Literal[*US_STATES]``, ``zip`` is
  :class:`ZipText` (required).
- :class:`LocationPartial` — Update shape: each subfield is independently
  ``T | None = None`` so partial patches can touch one subfield without
  forcing the others.

``extra="forbid"`` on both rejects unknown subkeys — the embedding
schemas already enforce this at the top level, but the value object owns
its own grammar.

The :func:`gather_flat_location` and :func:`flatten_location_on_dump`
helpers below are the wiring used by embedding schemas to keep the
wire/JSON shape flat (form posts send ``location_city`` etc.; JSON
responses and audit snapshots expose ``location_city`` etc. at the top
level) while the in-Python attribute is a single ``location`` value
object. New schemas embedding ``Location`` reuse these two helpers
verbatim.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer, model_validator

from src.domain.models.enums import US_STATES
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import StrippedText, ZipText

# `maxlength=120` is the client-side hint inherited from the pre-#451
# `ClinicianCreate.location_city` annotation. ``HtmlPattern`` is a form-
# rendering hint only (see :mod:`src.framework.rendering.form_fields`);
# Pydantic doesn't apply it as a server-side length cap. Client-referral
# forms don't read the hint (their template uses ``text_field`` directly
# instead of ``field_for``), so attaching it on the shared value object
# only affects the clinician form — which is the contract preserved here.
_CityText = Annotated[StrippedText, HtmlPattern(maxlength=120)]
_CityTextOptional = Annotated[StrippedText | None, HtmlPattern(maxlength=120)]

# Sub-field names on :class:`Location` / :class:`LocationPartial`.
# Kept here so the gather/flatten helpers below can iterate without
# importing model_fields at call time.
_LOCATION_SUBFIELDS: tuple[str, ...] = ("city", "state", "zip")


class Location(BaseModel):
    """``(city, state, zip)`` triple — required-state flavor.

    Used by Create and Read variants of the Clinician and client-referral
    schemas. All three subfields are required and run through the shared
    cleaning rules (:class:`StrippedText` for city, ``Literal[*US_STATES]``
    for state, :class:`ZipText` for zip)."""

    model_config = ConfigDict(extra="forbid")

    city: _CityText
    state: Literal[*US_STATES]
    zip: ZipText


class LocationPartial(BaseModel):
    """``(city, state, zip)`` triple — partial-update flavor.

    Each subfield is ``T | None = None``: an Update payload can touch
    ``location.city`` without restating ``location.state`` /
    ``location.zip``. The embedding Update schema's at-least-one-field
    rule treats the whole ``location`` field, so a ``location`` block
    that's present-but-empty (every subfield ``None``) still counts as
    a no-op patch at the top level."""

    model_config = ConfigDict(extra="forbid")

    city: _CityTextOptional = None
    state: Literal[*US_STATES] | None = None
    zip: ZipText | None = None


def gather_flat_location(data: Any) -> Any:
    """Pre-validation flatten-to-nest hook for schemas embedding
    ``location``.

    Handles two input shapes:

    1. **Dict** (form posts, JSON bodies, in-memory test payloads, the
       already-flat ``Post`` dict produced by
       ``_flatten_post_to_dict``): if any of ``location_city`` /
       ``location_state`` / ``location_zip`` is a top-level key, group
       them under a nested ``"location"`` key so the embedding
       schema's ``location: Location`` /
       ``location: LocationPartial`` field can validate. Keys whose
       value is unset (the dict simply doesn't have them) are left
       out, which lets partial-Update payloads touch just one
       location subfield.
    2. **Attribute bag** (an ORM row via :mod:`SimpleNamespace`, a
       SQLAlchemy mapper output, or any other ``from_attributes``-
       compatible carrier): if the object exposes flat
       ``location_<sub>`` attributes but no ``location`` attribute,
       attach a transient ``location`` attribute holding the nested
       dict so Pydantic's per-field ``from_attributes`` look-up finds
       the value object. SQLAlchemy rows that already expose a
       ``location`` property via :class:`LocationMixin` skip this
       branch (their ``location`` attr is read directly).

    Only the three exact ``location_<sub>`` keys are consumed; any other
    ``location_*`` key on the same payload (a hypothetical sibling field)
    is left untouched. ``_LOCATION_SUBFIELDS`` is the closed alphabet for
    this value object.

    If the input already has a ``"location"`` key/attribute the helper
    preserves it (no double-wrapping); a payload that sends *both*
    nested and flat in a dict merges the flat ones into the nested
    dict, which fails ``Location``'s own ``extra="forbid"`` rule if
    any subkey conflicts.
    """
    flat_keys = tuple(f"location_{k}" for k in _LOCATION_SUBFIELDS)
    if isinstance(data, dict):
        if not any(k in data for k in flat_keys):
            return data
        out = {k: v for k, v in data.items() if k not in flat_keys}
        nested = dict(data.get("location") or {})
        for sub in _LOCATION_SUBFIELDS:
            key = f"location_{sub}"
            if key in data:
                v = data[key]
                # Empty string from a blank form field → treat as absent
                if isinstance(v, str) and not v.strip():
                    v = None
                nested[sub] = v
        # When every subfield is absent or None the clinician has no location
        # yet.  Setting location=None lets schemas with `location: Location |
        # None = None` accept the payload without 422-ing on missing required
        # subfields.  Partial location (some fields present, some None) is
        # forwarded as-is so LocationPartial updates work correctly.
        if all(nested.get(sub) is None for sub in _LOCATION_SUBFIELDS):
            out["location"] = None
        else:
            out["location"] = nested
        return out
    # Attribute-bag branch: SimpleNamespace (contract-test mocks),
    # SQLAlchemy rows from older code paths that didn't pick up the
    # mixin's ``location`` property, etc.
    sentinel = object()
    if getattr(data, "location", sentinel) is not sentinel:
        return data
    flat_attrs = {
        sub: getattr(data, f"location_{sub}")
        for sub in _LOCATION_SUBFIELDS
        if getattr(data, f"location_{sub}", sentinel) is not sentinel
    }
    if not flat_attrs:
        return data
    # Mirrors the dict branch: all-None subfields mean "no location yet"
    # (deferred onboarding path) — set location=None so Location | None
    # schemas accept the payload without 422-ing on missing required subfields.
    if all(v is None for v in flat_attrs.values()):
        location_value: dict | None = None
    else:
        location_value = flat_attrs
    try:
        setattr(data, "location", location_value)
    except (AttributeError, TypeError):
        # Immutable / slot-bound bags can't take new attrs; downstream
        # validation will surface a helpful error.
        pass
    return data


def flatten_location_on_dump(model: BaseModel, data: dict[str, Any]) -> dict[str, Any]:
    """Post-serialization flatten-on-dump hook for schemas embedding
    ``location``.

    Inverse of :func:`gather_flat_location`. Takes a serialized dict
    that has a nested ``"location": {...}`` block and rewrites it to
    flat ``"location_<sub>"`` keys at the top level — so JSON responses,
    audit ``before`` / ``after`` snapshots, and the ORM-hydrating
    ``model_dump()`` call in the dispatch handlers all see the same
    flat shape they saw before the value object was introduced.

    Used inside a ``@model_serializer(mode="wrap")`` on the embedding
    schema. Subfields that are absent from the nested block (which can
    happen on partial-update dumps with ``exclude_unset=True``) are
    omitted from the output rather than written as ``None``, so
    ``payload.model_dump(exclude_unset=True)`` on a patch that only
    touched ``location.city`` produces ``{"location_city": ...}`` and
    not ``{"location_city": ..., "location_state": None, "location_zip": None}``.
    """
    _absent = object()
    nested = data.pop("location", _absent)
    if nested is _absent:
        # `location` key was absent (e.g. model_dump(exclude_unset=True) on an
        # Update that didn't touch location) — leave the dict untouched.
        return data
    if nested is None:
        # location was explicitly None — write explicit nulls so the wire shape
        # is stable (consumers always see location_city / _state / _zip, just null).
        for sub in _LOCATION_SUBFIELDS:
            data[f"location_{sub}"] = None
        return data
    if not isinstance(nested, dict):
        # Shouldn't happen in practice, but be defensive — restore the
        # key so the caller doesn't silently lose data.
        data["location"] = nested
        return data
    for sub in _LOCATION_SUBFIELDS:
        if sub in nested:
            data[f"location_{sub}"] = nested[sub]
    return data


class FlatLocationSchema(BaseModel):
    """Mixin for schemas that embed `Location` (or `LocationPartial`) and
    need to keep `(location_city, location_state, location_zip)` flat on
    the wire while modeling them as a single `location` value object in
    Python.

    Composes `gather_flat_location` (pre-validate) and
    `flatten_location_on_dump` (serialize) so each embedding schema
    inherits this mixin alongside its usual base
    (`ReadProjection`, `WirePayload`, `PartialUpdate`) instead of
    re-declaring the same two decorators per class.

    Example:

        class FooCreate(FlatLocationSchema, WirePayload):
            location: Location
            ...

    Don't use this mixin on the polymorphic Post schemas — those compose
    the gather hook with `_flatten_post_to_dict` and need to keep their
    bespoke `@model_validator(mode="before")` to control the
    composition order.
    """

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location_on_dump(self, handler):
        return flatten_location_on_dump(self, handler(self))
