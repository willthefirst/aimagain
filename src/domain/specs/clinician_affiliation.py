"""`CLINICIAN_AFFILIATION_ENTITY`: clinician × org practice-role sub-resource of Clinician.

Owned subentity of Clinician. Routes nest under
``/clinicians/{clinician_id}/clinician_affiliations/{affiliation_id}``. The
clinician edit page surfaces them as an inline list (same UX pattern
as licensures — see `src/domain/specs/clinician_licensure.py`); each row
is independently created, updated, or deleted via the framework's
sub-resource CRUD factories.

Read by `src/domain/routes/clinicians.py` (registers the entity as an
owned subentity of `CLINICIAN_ENTITY` via `mount_entity`).

A Clinician may hold multiple Affiliation rows; before that there was
a UNIQUE constraint on the FK column.
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
from src.domain.models import ClinicianAffiliation
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
    # Sub-row CRUD only — list/detail/form pages are owned by the
    # parent's `RelatedListSubresource` (`/clinicians/{id}/clinician_affiliations`,
    # #1336) which renders the inline add + per-row delete affordances.
    routes=RouteSet(create=True, update=True, delete=True),
    # Sub-row mutations redirect HTMX clients back to the sub-resource's
    # own list page — the page the user is already on after #1336.
    create_redirect=_clinician_affiliations_list_redirect,
    update_redirect=_clinician_affiliations_list_redirect,
    delete_redirect=_clinician_affiliations_list_redirect,
)
