"""`AFFILIATION_ENTITY`: clinician × org practice-role sub-resource of Clinician.

Owned subentity of Clinician. Routes nest under
``/clinicians/{clinician_id}/affiliations/{affiliation_id}``. The
clinician edit page surfaces them as an inline list (same UX pattern
as licensures — see `src/domain/specs/provider_licensure.py`); each row
is independently created, updated, or deleted via the framework's
sub-resource CRUD factories.

Read by `src/domain/routes/providers.py` (registers the entity as an
owned subentity of `CLINICIAN_ENTITY` via `mount_entity`).

A Clinician may hold multiple Affiliation rows; before that there was
a UNIQUE constraint on the FK column.
"""

from typing import Final

from src.domain.logic.affiliations.repository import get_affiliation_repository
from src.domain.logic.affiliations.schema import (
    AffiliationCreate,
    AffiliationRead,
    AffiliationUpdate,
)
from src.domain.models import Affiliation
from src.domain.specs.clinician import CLINICIAN_ENTITY, _clinician_form_redirect
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
)

AFFILIATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="affiliation",
    url_collection="affiliations",
    id_param="affiliation_id",
    model=Affiliation,
    parent=CLINICIAN_ENTITY,
    # Default check compares `affiliation.clinician_id == parent.id`
    # (derived from `spec.parent.name` = "clinician"). That is exactly
    # the FK we have after removing `affiliations.provider_id`. No
    # override needed.
    repo_dep=get_affiliation_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=AffiliationCreate,
    update_adapter=AffiliationUpdate,
    read_schema=AffiliationRead,
    # Sub-row CRUD only — affiliations are managed inline on the
    # parent clinician's edit page; no independent list/detail surface.
    routes=RouteSet(create=True, update=True, delete=True),
    # Sub-row mutations redirect HTMX clients back to the parent
    # clinician's edit form so the user keeps editing in place.
    create_redirect=_clinician_form_redirect,
    update_redirect=_clinician_form_redirect,
    delete_redirect=_clinician_form_redirect,
)
