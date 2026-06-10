"""`LICENSURE_ENTITY`: clinician's licensure credential subentity.

Owned subentity of `Clinician`: routes nest under
``/clinicians/{clinician_id}/licensures/{licensure_id}``. Base shape
(CRUD) is identical to the other clinician credentials — see
`_credential.py` for the shared factory. License attestation is the
only credential-specific addition: a state axis at
``PUT /clinicians/{clinician_id}/licensures/{licensure_id}/attestation``
that flips `attested_active=True`. The owning clinician's Claim-A
cache is recomputed for symmetry with other licensure transitions,
but licensure status no longer gates the claim — only `npi_match_status`
does.

Read by `src/domain/routes/clinicians.py` (derives `LICENSURE_SPEC` for
the mount helpers).
"""

from typing import Final

from pydantic import BaseModel

from src.domain.logic.clinicians.schema import (
    ClinicianLicensureCreate,
    ClinicianLicensureRead,
    ClinicianLicensureUpdate,
)
from src.domain.models import ClinicianLicensure
from src.domain.specs._credential import make_clinician_credential_entity
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import EntitySpec, StateAxis


class _LicenseAttestationBody(BaseModel):
    """Body for the attestation axis. Empty payload — the act of
    POSTing the URL IS the attestation. A field is reserved for future
    refusal flows (e.g. "I attest this license is NOT active" to
    proactively flip `status='expired'`)."""

    # `attested: bool = True` keeps the shape forward-compatible while
    # accepting an empty `{}` body (default-True). Clients that want
    # to be explicit can POST `{"attested": true}`.
    attested: bool = True


def _attestation_response_to_dict(licensure: ClinicianLicensure) -> dict:
    return {
        "id": str(licensure.id),
        "status": licensure.status,
        "attested_active": licensure.attested_active,
    }


LICENSURE_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_licensure",
    url_collection="licensures",
    id_param="licensure_id",
    model=ClinicianLicensure,
    audit_stem="licensure",
    read_schema=ClinicianLicensureRead,
    create_adapter=ClinicianLicensureCreate,
    update_adapter=ClinicianLicensureUpdate,
    state_axes=(
        StateAxis(
            name="attestation",
            body_schema=_LicenseAttestationBody,
            action=AuditAction.SET_LICENSE_ATTESTATION,
            response_to_dict=_attestation_response_to_dict,
            handler_path=(
                "src.domain.logic.clinicians.handlers" ".handle_set_license_attestation"
            ),
            audit_snapshot=ClinicianLicensureRead,
            forbid_self=False,
        ),
    ),
)
