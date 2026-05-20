"""`AFFILIATION_ENTITY`: clinician × org practice-role sub-resource of `Provider`.

Owned subentity of `Provider` (URL family `/clinicians/...` after
#642 PR 4 — the Python model stays `Provider`, only the user-facing
surface flipped). Routes nest under
``/clinicians/{clinician_id}/affiliations/{affiliation_id}``. The
clinician edit page surfaces them as an inline list (same UX pattern
as licensures — see `src/domain/specs/provider_licensure.py`); each row
is independently created, updated, or deleted via the framework's
sub-resource CRUD factories.

Read by `src/domain/routes/providers.py` (registers the entity as an
owned subentity of `PROVIDER_ENTITY` via `mount_entity`).

The 1:N relationship (Provider holds many Affiliations) became
possible in `7c3c296c9429` (#642 PR 1); before that the
`affiliations.provider_id` column was UNIQUE.
"""

from typing import Final

from src.domain.logic.affiliations.repository import get_affiliation_repository
from src.domain.logic.affiliations.schema import (
    AffiliationCreate,
    AffiliationRead,
    AffiliationUpdate,
)
from src.domain.models import Affiliation
from src.domain.specs.provider import PROVIDER_ENTITY, _provider_form_redirect
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
    parent=PROVIDER_ENTITY,
    # `child_parent_match_attr` is left at the default — the
    # framework's URL-vs-row consistency check then compares
    # `affiliation.provider_id == parent.id`, which is exactly the
    # FK relationship we want. `parent_fk_attr` overrides the
    # default-path attr name: after #642 PR 4 the parent's
    # `spec.name` is "clinician" (user-facing rename), but the
    # FK column on `affiliations` kept its historical name
    # `provider_id` (the model class stays `Provider`). Without the
    # override the default would look for `affiliation.clinician_id
    # == parent.id`, which is wrong (`clinician_id` is the FK to
    # `clinicians.id`, not to the parent provider). The provider-
    # credential subentities take a different escape hatch
    # (`child_parent_match_attr`) because their FK targets a
    # non-parent table.
    parent_fk_attr="provider_id",
    repo_dep=get_affiliation_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=AffiliationCreate,
    update_adapter=AffiliationUpdate,
    read_schema=AffiliationRead,
    # Sub-row CRUD only — affiliations are managed inline on the
    # parent provider's edit page; no independent list/detail surface.
    routes=RouteSet(create=True, update=True, delete=True),
    # Sub-row mutations redirect HTMX clients back to the parent
    # provider's edit form so the user keeps editing in place.
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    delete_redirect=_provider_form_redirect,
)
