"""`SAVED_SEARCH_ENTITY`: a user's saved post-directory searches.

Owned subentity of `User`. Routes nest under
``/users/{user_id}/saved_searches/{saved_search_id}``.

This is the codebase's first ``parent=USER_ENTITY`` owned subentity
(clinicians / organizations are *top-level* user-owned resources keyed
by ``owner_id``; the credentials/affiliations are owned by *Clinician*).
Two consequences of the parent being the user itself:

- **Auth is self-or-admin, not owner-or-admin.** The framework runs
  ``write_authz`` against the loaded *parent* row — here a ``User`` —
  on create / update / delete / edit-form. ``assert_owner_or_admin``
  would read ``user.owner_id`` (a user has none); the right rule is
  ``assert_self_or_admin`` (``actor.id == user.id`` or admin). Hand-wired
  rather than via the ``OWNER_OR_ADMIN`` sentinel for exactly that
  reason.
- **The list verb needs a bespoke handler.** The generic list mount
  doesn't gate by parent, and a saved search is private — so the list
  is wired through ``mount_entity``'s ``owned_handlers`` to
  ``handle_list_saved_searches`` (same self-or-admin gate the user's
  clinician related-list uses). See `src/domain/routes/users.py`.

Read by `src/domain/routes/users.py` (mounts the child under
``USER_ENTITY``).
"""

from typing import Final

from src.domain.logic.saved_searches.repository import get_saved_search_repository
from src.domain.logic.saved_searches.schema import (
    SavedSearchCreate,
    SavedSearchRead,
    SavedSearchUpdate,
)
from src.domain.models import SavedSearch
from src.domain.specs.user import USER_ENTITY
from src.framework.access.authz.authz import assert_self_or_admin
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    EntitySpec,
    Redirects,
    RouteSet,
)

# Post-mutation redirect: HTMX clients land back on the saved-search
# list page (the page the create/edit/delete action was taken from).
_saved_searches_list_redirect = Redirects.to_related_list(
    "users", "user_id", "saved_searches"
)


SAVED_SEARCH_ENTITY: Final[EntitySpec] = EntitySpec(
    name="saved_search",
    singular_label="saved search",
    url_collection="saved_searches",
    id_param="saved_search_id",
    model=SavedSearch,
    parent=USER_ENTITY,
    # Default FK convention: child holds ``<parent.name>_id`` = "user_id"
    # (parent entity name is "user"). That is exactly our owner FK, so no
    # ``parent_fk_attr`` / ``child_parent_match_attr`` override is needed.
    repo_dep=get_saved_search_repository,
    auth_deps=AUTHENTICATED,
    # Parent is the user itself → self-or-admin, not owner-or-admin. The
    # generic mounts call this as ``write_authz(parent_user, actor,
    # action=...)``, matching ``assert_self_or_admin(target, actor, *,
    # action)``.
    write_authz=assert_self_or_admin,
    create_adapter=SavedSearchCreate,
    update_adapter=SavedSearchUpdate,
    read_schema=SavedSearchRead,
    audit_snapshot=SavedSearchRead,
    routes=RouteSet(
        list=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    create_redirect=_saved_searches_list_redirect,
    update_redirect=_saved_searches_list_redirect,
    delete_redirect=_saved_searches_list_redirect,
)
