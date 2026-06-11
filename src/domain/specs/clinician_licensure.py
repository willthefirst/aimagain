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
from src.domain.models.enums import LICENSE_TYPES, LICENSE_TYPES_LABELS, US_STATES
from src.domain.specs._credential import (
    CANONICAL_CREDENTIAL_ROUTES,
    make_clinician_credential_entity,
)
from src.domain.specs.clinician import _clinician_licensures_list_redirect
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
    mutation_redirect=_clinician_licensures_list_redirect,
    # Licensure is the first credential converted to the canonical
    # resource pattern: dedicated list at /clinicians/{id}/licensures
    # with a "Create licensure" toolbar action, dedicated create-form
    # at /licensures/form, and dedicated edit-form at /licensures/{id}/form
    # with Delete + Attest active in the actions cluster. The list page's
    # `RelatedListSubresource` on CLINICIAN_ENTITY is removed to avoid
    # double-mount; the bespoke handle_list_clinician_licensures handler
    # is wired through `mount_entity`'s owned_handlers in
    # `src/domain/routes/clinicians.py`.
    routes=CANONICAL_CREDENTIAL_ROUTES,
    # The list / form templates reference the license-type tuple +
    # labels and US_STATES. Surfacing them via static_context (instead
    # of Jinja globals) keeps the spec the single source of truth for
    # what the licensure templates see.
    static_context={
        "LICENSE_TYPES": LICENSE_TYPES,
        "LICENSE_TYPES_LABELS": LICENSE_TYPES_LABELS,
        "US_STATES": US_STATES,
    },
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
