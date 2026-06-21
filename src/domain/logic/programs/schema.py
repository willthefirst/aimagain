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

The Program holds only the steady-state context that doesn't vary per
intake window: ``state_preference``, intake dates, ``accepting_referrals``,
``languages``, ``website`` / ``referral_instructions``. The
per-announcement profile (services / age groups / genders / cost) moved
onto ``IntakeDetail`` (the intake post).

No insurance fields — intentional grammar. Insurance is modeled on
:class:`Clinician` (who delivers care) and on per-Post detail rows;
Program is the offering, not the carrier of insurance.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator

from src.domain.models.enums import (
    LANGUAGES,
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

# `languages` is program-level (a program may operate in a different
# language set than any individual clinician staffing it). Same
# `list[Literal[*TUPLE]] + scalar_to_list` shape as the post schemas.
_LanguagesField = Annotated[list[Literal[*LANGUAGES]], BeforeValidator(scalar_to_list)]
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
    # `languages` lives on Program (and on Clinician) because a program may
    # operate in a different language set than any individual clinician
    # staffing it. Defaults to `["en"]` matching the column's server-side
    # default. The per-announcement profile (services / age_groups /
    # genders / cost) moved onto the intake post.
    languages: _LanguagesField = ["en"]
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
    # Defaults to `["en"]` matching the column's server-side default.
    # Create accepts an explicit list so a brand-new program records
    # its language set on day one. The per-announcement profile moved to
    # the intake post.
    languages: _LanguagesField = ["en"]
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
    # List-valued PATCH replaces the whole list. `None` = leave
    # unchanged. `[]` = clear (no languages stated).
    languages: _LanguagesField | None = None
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None
