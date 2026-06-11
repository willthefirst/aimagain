"""`CLINICIAN_AFFILIATION_ENTITY`: clinician × org practice-role sub-resource of Clinician.

Owned subentity of Clinician. Routes nest under
``/clinicians/{clinician_id}/clinician_affiliations/{affiliation_id}``.

Migrated to the canonical resource pattern (PR 4 of 4 in the
canonical-sub-resource conversion): dedicated list + form_new +
form_edit pages instead of an inline add form on the list page. See
`src/domain/specs/clinician_licensure.py` for the first conversion
that established the shape.

A Clinician may hold multiple Affiliation rows.
"""

from typing import Final

from src.domain.logic.clinician_affiliations.repository import (
    get_clinician_affiliation_repository,
)
from src.domain.logic.clinician_affiliations.schema import (
    ClinicianAffiliationCreate,
    ClinicianAffiliationRead,
    ClinicianAffiliationUpdate,
)
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import ClinicianAffiliation
from src.domain.models.enums import (
    INSURANCE_CARRIER_LABELS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_LABELS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.domain.specs.clinician import (
    CLINICIAN_ENTITY,
    _clinician_affiliations_list_redirect,
)
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
)

CLINICIAN_AFFILIATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="clinician_affiliation",
    # The DB model + URL slug call them affiliations because that's
    # what the (clinician × org) join is; the UI calls them "practices"
    # because that's what they are to the user. The `singular_label`
    # carries the UI noun so chrome labels read "Create practice" /
    # "Edit practice" instead of "Edit clinician_affiliation".
    singular_label="practice",
    url_collection="clinician_affiliations",
    id_param="clinician_affiliation_id",
    model=ClinicianAffiliation,
    parent=CLINICIAN_ENTITY,
    # Default check compares `affiliation.clinician_id == parent.id`
    # (derived from `spec.parent.name` = "clinician"). That is exactly
    # the FK we have after removing `affiliations.provider_id`. No
    # override needed.
    repo_dep=get_clinician_affiliation_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=ClinicianAffiliationCreate,
    update_adapter=ClinicianAffiliationUpdate,
    read_schema=ClinicianAffiliationRead,
    # Canonical resource pattern: dedicated list +
    # `/clinicians/{id}/clinician_affiliations/form` create page +
    # `/clinicians/{id}/clinician_affiliations/{aff_id}/form` edit page
    # (Delete in the actions cluster). The parent's
    # `RelatedListSubresource` entry for affiliations is removed in
    # `src/domain/specs/clinician.py` (no double-mount); the bespoke
    # `handle_list_clinician_affiliations` handler is wired through
    # `mount_entity`'s `owned_handlers` in
    # `src/domain/routes/clinicians.py`.
    routes=RouteSet(
        list=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    # Sub-row mutations redirect HTMX clients back to the sub-resource's
    # own list page — the page the user is already on after #1336.
    create_redirect=_clinician_affiliations_list_redirect,
    update_redirect=_clinician_affiliations_list_redirect,
    delete_redirect=_clinician_affiliations_list_redirect,
    # The affiliation form templates reference controlled-vocabulary
    # constants (US_STATES, INSURANCE_CARRIERS, etc.); surface them via
    # static_context so the templates don't depend on Jinja-global
    # injection (which only fires inside CLINICIAN_ENTITY's chrome).
    static_context={
        "US_STATES": US_STATES,
        "INSURANCE_CARRIERS": INSURANCE_CARRIERS,
        "INSURANCE_CARRIER_LABELS": INSURANCE_CARRIER_LABELS,
        "LOCATION_AVAILABILITY_OPTIONS": LOCATION_AVAILABILITY_OPTIONS,
        "LOCATION_AVAILABILITY_LABELS": LOCATION_AVAILABILITY_LABELS,
    },
    # Both the create and edit form templates render an Organization
    # picker scoped to the viewer's visible orgs. The hook lives in
    # the clinicians logic module (the picker is shared between the
    # clinician edit page and the affiliation forms — same query).
    form_extras_path=("src.domain.logic.clinicians.handlers.clinician_form_extras"),
    form_extras_repos=(("organization_repo", OrganizationRepository),),
)
