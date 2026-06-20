# Saved searches logic cluster

Per-user, CRUD-able named filtered views of the post directory. Owned subentity of `User` — routes nest under `/users/{user_id}/saved_searches`. Spec: [`../../specs/saved_search.py`](../../specs/saved_search.py). Model + the structured-JSON-vs-stored-URL rationale: [`../../models/saved_searches/README.md`](../../models/saved_searches/README.md).

## Files

- `schema.py` — `SavedSearchCreate` / `SavedSearchUpdate` / `SavedSearchRead`. A saved search is `name` + a `filters` dict (the persisted `filter_values` shape). Filter-vocabulary validation against the live `POST_ENTITY.filters` names is **not** here yet — PR1 round-trips any JSON object; the capture/round-trip PR adds it alongside the URL helpers that consume the dict.
- `repository.py` — `SavedSearchRepository`, a thin `BaseRepository` shell. The owner-scoped listing reuses `BaseRepository.list_owned_by(SavedSearch, user_id, owner_attr="user_id")`.
- `handlers.py` — `handle_list_saved_searches`, the **only** bespoke verb. The other CRUD verbs are framework-generic.

## Why only the list verb is bespoke

Create / update / delete / form-edit run `write_authz` (`assert_self_or_admin`) against the loaded **parent user** inside the generic mounts — so they're already gated to owner-or-admin. The generic *list* mount has no per-parent gate; it would let any authenticated viewer read `/users/{other_id}/saved_searches`. A saved search is private, so the list is hand-written with the same self-or-admin gate the user's clinician related-list (`handle_list_user_clinicians`) uses, and wired through `mount_entity`'s `owned_handlers` in [`../../routes/users.py`](../../routes/users.py).

## Why self-or-admin, not owner-or-admin

This is the first `parent=USER_ENTITY` owned subentity. The framework runs `write_authz` against the parent row — here a `User`, which has no `owner_id`. `OWNER_OR_ADMIN` would read a missing column; the correct rule is `assert_self_or_admin` (`actor.id == user.id` or admin). See the spec docstring.
