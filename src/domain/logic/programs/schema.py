"""Wire schemas for the `Program` entity.

A :class:`Program` is a treatment offering owned by an
:class:`Organization` (PR 4 of the Org/Program roadmap, #537). The
wire surface mirrors Provider's shape post-#524 — ``ProgramRead``
carries an inline ``org_name`` (sourced from
``program.organization.name`` via ``from_attributes``) so templates
and audit snapshots read a flat string without dereferencing the
relationship.

Controlled-vocabulary fields (``state_preference`` against
:data:`US_STATES`) are typed as ``Literal[*TUPLE] | None`` so the
schema's accepted values stay in lockstep with the DB CHECK
constraint.

No insurance fields — intentional grammar. Insurance is modeled on
:class:`Provider` (who delivers care) and on per-Post detail rows;
Program is the offering, not the carrier of insurance.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from src.domain.models.enums import US_STATES
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
)


class ProgramRead(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # ``org_id`` is the FK to the owning Organization; ``org_name`` is
    # the Org's display name, sourced from
    # ``program.organization.name`` via ``from_attributes`` (same
    # inline-field shape as ``ProviderRead`` post-#524).
    org_id: uuid.UUID
    org_name: str
    name: str
    description: str | None = None
    state_preference: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    accepting_referrals: bool


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
