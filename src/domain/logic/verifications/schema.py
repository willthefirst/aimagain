"""Wire schemas for `Verification`.

Server-only surface. `Verification` has no public CRUD endpoints — the
nightly job and a superuser-only retrigger endpoint both write rows via
:class:`VerificationCreate`, and the admin UI reads via
:class:`VerificationRead`. There are no `Update` / `Delete` schemas
because verification rows are append-only by convention.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from src.domain.models.enums import VERIFICATION_STATUSES
from src.framework.schema_validators import ReadProjection, WirePayload


class VerificationRead(ReadProjection):
    id: uuid.UUID
    provider_id: uuid.UUID
    status: str
    flags: list[str] = []
    nppes_result: dict[str, Any] | None = None
    oig_match: bool
    name_match_score: float | None = None
    created_at: datetime
    updated_at: datetime


class VerificationCreate(WirePayload):
    """Server-only payload: composed by the orchestrator in
    `handlers.py` (#528 / A4) from the NPPES / OIG check results and the
    scoring function. Not accepted from any wire surface."""

    provider_id: uuid.UUID
    status: Literal[*VERIFICATION_STATUSES]
    flags: list[str] = []
    nppes_result: dict[str, Any] | None = None
    oig_match: bool = False
    name_match_score: float | None = None
