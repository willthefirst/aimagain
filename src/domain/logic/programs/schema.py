"""Wire schemas for the `Program` entity.

A :class:`Program` is a treatment offering owned by an
:class:`Organization`. The wire surface mirrors Clinician's shape —
``ProgramRead`` carries an inline ``org_name`` (sourced from
``program.organization.name`` via ``from_attributes``) so templates
and audit snapshots read a flat string without dereferencing the
relationship.

Controlled-vocabulary fields (``state_preference`` against
:data:`US_STATES`) are typed as ``Literal[*TUPLE] | None`` so the
schema's accepted values stay in lockstep with the DB CHECK
constraint.

The steady-state practice profile (``services`` / ``settings`` /
``modalities`` / ``age_groups`` / ``genders`` / ``website`` /
``referral_instructions``) lives on this entity since #1358 PR-f
(moved off ``IntakeDetail``). Multi-select fields use the same
``list[Literal[*TUPLE]] + scalar_to_list`` shape as the post
schemas — the `BeforeValidator` normalizes a 1-element form post
(scalar string) into a list before the per-member `Literal` check
fires. Empty list means "no value provided".

No insurance fields — intentional grammar. Insurance is modeled on
:class:`Clinician` (who delivers care) and on per-Post detail rows;
Program is the offering, not the carrier of insurance.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator

from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    GENDERS,
    REFERRAL_SERVICES,
    TREATMENT_MODALITIES,
    TREATMENT_SETTINGS,
    US_STATES,
)
from src.framework.rendering.form_fields import HtmlTextarea, HtmlUrl
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
    scalar_to_list,
)

# Steady-state-profile multi-select aliases. Shape mirrors the
# `ServicesField`/`SettingsField`/etc. aliases in `posts/schema.py` —
# each layers a `Literal[*TUPLE]` over the shared `scalar_to_list`
# coercion so a 1-checkbox-checked form post still validates.
_ServicesField = Annotated[
    list[Literal[*REFERRAL_SERVICES]], BeforeValidator(scalar_to_list)
]
_SettingsField = Annotated[
    list[Literal[*TREATMENT_SETTINGS]], BeforeValidator(scalar_to_list)
]
_ModalitiesField = Annotated[
    list[Literal[*TREATMENT_MODALITIES]], BeforeValidator(scalar_to_list)
]
_AgeGroupsField = Annotated[
    list[Literal[*CLIENT_AGE_GROUPS]], BeforeValidator(scalar_to_list)
]
_GendersField = Annotated[list[Literal[*GENDERS]], BeforeValidator(scalar_to_list)]
# Free-text fields. `website` is rendered as `<input type=url>` (the
# `HtmlUrl` marker drives `field_for`). `referral_instructions` renders
# as `<textarea>`. Both stripped-to-None on blank input.
_WebsiteField = Annotated[StrippedOptionalText, HtmlUrl()]
_ReferralInstructionsField = Annotated[StrippedOptionalText, HtmlTextarea()]


class ProgramRead(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # ``org_id`` is the FK to the owning Organization; ``org_name`` is
    # the Org's display name, sourced from
    # ``program.organization.name`` via ``from_attributes`` (same
    # inline-field shape as ``ClinicianRead`` post-#524).
    org_id: uuid.UUID
    org_name: str
    name: str
    description: str | None = None
    state_preference: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    accepting_referrals: bool
    # Steady-state profile (#1358 PR-f).
    services: _ServicesField = []
    settings: _SettingsField = []
    modalities: _ModalitiesField = []
    age_groups: _AgeGroupsField = []
    genders: _GendersField = []
    website: str | None = None
    referral_instructions: str | None = None


class ProgramCreate(WirePayload):
    """Create payload. ``owner_id`` is set by the route from the
    authenticated user, not accepted on the wire.

    The ``Org`` the Program attaches to is identified by ``org_id``;
    users who need a new Org create it via
    ``POST /organizations`` first. The Org-picker dropdown on the
    create form is populated by ``program_form_extras`` (the spec's
    ``form_extras_path``), scoped to the user's owned Orgs.
    """

    org_id: uuid.UUID
    name: StrippedText
    description: StrippedOptionalText = None
    state_preference: Literal[*US_STATES] | None = None
    start_date: date | None = None
    end_date: date | None = None
    accepting_referrals: bool = True
    # Steady-state profile (#1358 PR-f). Empty list = "no value
    # provided"; mirrors how the post schemas default these.
    services: _ServicesField = []
    settings: _SettingsField = []
    modalities: _ModalitiesField = []
    age_groups: _AgeGroupsField = []
    genders: _GendersField = []
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None


class ProgramUpdate(PartialUpdate):
    """Partial update. Touching ``org_id`` reassigns the Program to a
    different Organization — wire-side authz on the new ``org_id``
    runs through
    :func:`src.domain.logic.programs.handlers._assert_program_payload_org_ownership`
    via the spec's ``payload_authz_path`` hook."""

    org_id: uuid.UUID | None = None
    name: StrippedText | None = None
    description: StrippedOptionalText = None
    state_preference: Literal[*US_STATES] | None = None
    start_date: date | None = None
    end_date: date | None = None
    accepting_referrals: bool | None = None
    # List-valued PATCH replaces the whole list, matching the same-named
    # fields on `ReferralUpdate` / `ClinicianOpeningUpdate`.
    services: _ServicesField | None = None
    settings: _SettingsField | None = None
    modalities: _ModalitiesField | None = None
    age_groups: _AgeGroupsField | None = None
    genders: _GendersField | None = None
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None
