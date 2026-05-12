"""Wire schemas for provider and its credential sub-entities.

A `Provider` is a long-lived directory entry owned by a `User`
(N:1 via `owner_id` — a user may own zero, one, or many providers). It
holds three credential lists —
`ProviderLicensure`, `ProviderEducation`, `ProviderCertification` —
each managed via its own endpoints in later issues. The wire surface
mirrors that shape: each entity has Read / Create / Update variants.

Audit snapshots for every provider entity are byte-identical to the
matching `Read` schema, so each `EntitySpec` reads its audit shape
through `read_schema` directly — `EntitySpec.__post_init__` defaults
`audit_snapshot` to `read_schema` when the latter is a Pydantic class.
This module therefore declares no `*AuditSnapshot` symbols; posts and
users genuinely diverge (kind-discriminated flatten / omitted id) and
keep distinct classes — see those modules.

`ProviderRead` embeds the sub-entity Read lists. `ProviderUpdate` does
**not** include nested lists — sub-entities are PATCHed via their own
routes (added later), so a provider-level PATCH only touches the
practice/availability fields.

Controlled-vocabulary fields (state, license type, etc.) are typed as
`Literal[*TUPLE]` against the tuples in `src/domain/models/enums.py` so
the schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields reuse `StrippedText` and `ZipText` from
[`src/framework/schema_validators.py`](_validators.py) — defining them once
means one source of truth for the cleaning rule.

A guardrail test in `test_provider.py`
(`test_schema_literals_match_model_tuples`) keeps the `Literal`
universes aligned with the source tuples.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, model_serializer, model_validator

from src.domain.logic.value_objects.location import (
    Location,
    LocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
)
from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    INSURANCE_CARRIERS,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
)


def _scalar_to_list(v):
    """Wrap a single string in a one-element list. HTML form posts collapse
    a 1-checkbox-checked group to a scalar (htmx's `json-enc` only emits an
    array when the same name appears 2+ times); this normalizes that
    1-element case before the `Literal[*TUPLE]` member check fires. Mirrors
    the helper in `src/domain/logic/posts/schema.py`."""
    if isinstance(v, str):
        return [v]
    return v


# `in_network_carriers` is a multi-checkbox group; scalar→singleton coercion
# matches the pattern shared with PA/CR multi-select fields.
InNetworkCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(_scalar_to_list)
]


class _ProviderSubrowBase(ReadProjection):
    """Common fields for every provider sub-row Read schema (licensure /
    education / certification). Subclasses add entity-specific fields.
    Also serves as the audit-snapshot shape (see module docstring).
    """

    id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- ProviderLicensure --------------------------------------------------


class ProviderLicensureRead(_ProviderSubrowBase):
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None


class ProviderLicensureCreate(WirePayload):
    license_type: Literal[*LICENSE_TYPES]
    license_number: StrippedText
    issuing_state: Literal[*US_STATES]
    expiration_date: date | None = None


class ProviderLicensureUpdate(PartialUpdate):
    license_type: Literal[*LICENSE_TYPES] | None = None
    license_number: StrippedText | None = None
    issuing_state: Literal[*US_STATES] | None = None
    expiration_date: date | None = None


# --- ProviderEducation --------------------------------------------------


class ProviderEducationRead(_ProviderSubrowBase):
    education_type: str
    institution: str
    month_completed: str | None = None


class ProviderEducationCreate(WirePayload):
    education_type: Literal[*EDUCATION_TYPES]
    institution: StrippedText
    # `month_completed` is a "YYYY-MM" string per the model — month
    # precision only. Format validation is intentionally deferred to a
    # later issue once the form contract is settled.
    month_completed: str | None = None


class ProviderEducationUpdate(PartialUpdate):
    education_type: Literal[*EDUCATION_TYPES] | None = None
    institution: StrippedText | None = None
    month_completed: str | None = None


# --- ProviderCertification ----------------------------------------------


class ProviderCertificationRead(_ProviderSubrowBase):
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None


class ProviderCertificationCreate(WirePayload):
    certification_type: Literal[*CERTIFICATION_TYPES]
    certifying_body: StrippedText
    expiration_date: date | None = None


class ProviderCertificationUpdate(PartialUpdate):
    certification_type: Literal[*CERTIFICATION_TYPES] | None = None
    certifying_body: StrippedText | None = None
    expiration_date: date | None = None


# --- Provider ----------------------------------------------------


class ProviderRead(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    practice_name: str
    # `(city, state, zip)` arrive flat — from ORM attributes via
    # ``from_attributes`` or from a flat dict — and dump flat (JSON
    # responses still expose ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level). ``gather_flat_location`` rolls
    # the flat input into a nested ``location`` block before validation
    # so the ``Location`` value object owns the cleaning rules; the
    # ``@model_serializer`` below unrolls it back to flat on dump (#451).
    location: Location
    in_person_sessions: str
    virtual_sessions: str
    accepts_in_network: bool
    accepts_out_of_network: bool
    in_network_carriers: list[str] = []
    sliding_scale: bool
    cost: str | None = None
    licensures: list[ProviderLicensureRead] = []
    educations: list[ProviderEducationRead] = []
    certifications: list[ProviderCertificationRead] = []

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


def _check_in_network_carriers_invariant(
    accepts_in_network: bool | None, in_network_carriers: list[str] | None
) -> None:
    """Cross-field rule (#449): if `accepts_in_network=True`, the carrier
    list is required-min-1; if `False`, the list must be empty. Both
    arguments are non-`None` when this fires."""
    if accepts_in_network and not in_network_carriers:
        raise ValueError(
            "in_network_carriers must contain at least one carrier when "
            "accepts_in_network is True"
        )
    if not accepts_in_network and in_network_carriers:
        raise ValueError(
            "in_network_carriers must be empty when accepts_in_network is False"
        )


class ProviderCreate(WirePayload):
    """Create payload for a provider's directory provider. `owner_id` is
    set by the route from the authenticated user, not accepted on the
    wire.

    The ``(city, state, zip)`` location triple is modeled as a single
    :class:`Location` value object (#451). On the wire it stays flat —
    form posts and JSON bodies send ``location_city`` / ``location_state``
    / ``location_zip`` at the top level — the ``gather_flat_location``
    pre-validator rolls those keys into a nested ``location`` block,
    and the ``@model_serializer`` flattens the dump back to flat keys
    so JSON responses, ORM-hydrating ``model_dump()``, and audit
    snapshots keep the pre-#451 shape.
    """

    # `HtmlPattern(maxlength=...)` is a form-side hint only — does not
    # affect server-side validation. It exists so the rendered
    # `<input maxlength=...>` matches the previous hand-rolled form
    # without restating the number per template. Adding a true server-
    # side length cap (`pydantic.StringConstraints` etc.) is a separate
    # concern.
    practice_name: Annotated[StrippedText, HtmlPattern(maxlength=200)]
    location: Location
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    # Insurance posture (#449). `accepts_in_network` /
    # `accepts_out_of_network` are orthogonal Booleans; the carrier list
    # only applies when `accepts_in_network=True`. The cross-field rule
    # is enforced by `_check_in_network_carriers` below.
    accepts_in_network: bool = False
    accepts_out_of_network: bool = False
    in_network_carriers: InNetworkCarriersField = []
    sliding_scale: bool = False
    cost: StrippedOptionalText = None
    licensures: list[ProviderLicensureCreate] = []
    educations: list[ProviderEducationCreate] = []
    certifications: list[ProviderCertificationCreate] = []

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_validator(mode="after")
    def _check_in_network_carriers(self):
        _check_in_network_carriers_invariant(
            self.accepts_in_network, self.in_network_carriers
        )
        return self

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ProviderUpdate(PartialUpdate):
    """Partial update of practice/availability fields only. Sub-entity
    lists (licensures, educations, certifications) are managed via
    their own endpoints, so this schema does not accept them.

    Like :class:`ProviderCreate`, the location triple is embedded as a
    :class:`LocationPartial` value object — patches can touch one
    subfield independently (e.g. just ``location_city``) and the
    flatten-on-dump serializer keeps ``payload.model_dump(exclude_unset=True)``
    producing the same flat ``location_city`` shape the dispatch
    handler's ``repo.patch(target, **fields)`` call expects.
    """

    practice_name: StrippedText | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_in_network: bool | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_validator(mode="after")
    def _check_in_network_carriers(self):
        # Only enforce the cross-field rule when *both* fields are in the
        # patch — otherwise the route handler would have to merge with the
        # persisted row to know whether the invariant holds, which isn't
        # easily reachable from the schema layer. Patches that only touch
        # one of the two pass through; the other field's persisted value
        # may make the invariant hold or not, but that's the caller's
        # responsibility to keep coherent.
        if self.accepts_in_network is not None and self.in_network_carriers is not None:
            _check_in_network_carriers_invariant(
                self.accepts_in_network, self.in_network_carriers
            )
        return self

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))
