# Saved searches logic cluster

Per-user, CRUD-able named filtered views of the post directory. Owned subentity of `User` — routes nest under `/users/{user_id}/saved_searches`. Spec: [`../../specs/saved_search.py`](../../specs/saved_search.py). Model + the structured-JSON-vs-stored-URL rationale: [`../../models/saved_searches/README.md`](../../models/saved_searches/README.md).

## Files

- `schema.py` — `SavedSearchCreate` / `SavedSearchUpdate` / `SavedSearchRead`. A saved search is `name` + a `filters` dict (the persisted `filter_values` shape). `filters` accepts a real JSON object *or* a JSON string (the posts-page "Save this search" hidden field), then **drops keys that aren't currently-declared `/posts` filters** — the durability contract (a renamed/removed post filter degrades to "ignore that dimension", never a load failure). Values pass through; `/posts` validates them on use.
- `repository.py` — `SavedSearchRepository`, a thin `BaseRepository` shell. The owner-scoped listing reuses `BaseRepository.list_owned_by(SavedSearch, user_id, owner_attr="user_id")`.
- `handlers.py` — `handle_list_saved_searches`, the **only** bespoke verb. The other CRUD verbs are framework-generic.
- `urls.py` — `posts_url_for_filters(filters)`, the "open" half of the round-trip: renders the stored dict back into a `/posts?…` URL. Registered as a Jinja global in [`../../template_globals.py`](../../template_globals.py); the saved-search list card headline uses it. Serialization mirrors the active-filter query-string builder in `framework/dispatch/mounts/list_.py`.
- `defaults.py` — `DEFAULT_SAVED_SEARCHES` (openings + referrals) and `seed_default_saved_searches(session, user_id)`. The single source of truth for "what every user starts with", consumed by two paths: `UserManager.on_after_register` (`src/auth_config.py`) seeds every new account on the request session; the dev-seed override (`scripts/dev/seed/overrides/saved_searches.py`) gives each seeded user the same rows. The helper is name-idempotent (skips a default the user already has), which also makes the dev seed rerun-safe. It takes the caller's session — *not* a fresh one — so the seed lands in the same DB the rest of the request uses (and the DB tests override to).

## The round-trip

`/posts` filter form → `filter_values` dict → **capture** ("Save this search" on `posts/list.html`, hidden `filters` JSON) → stored dict → **open** (`posts_url_for_filters`) → `/posts?…`. The dict is canonical; the URL is derived at both ends, so URL-syntax changes never touch stored rows.

## Why only the list verb is bespoke

Create / update / delete / form-edit run `write_authz` (`assert_self_or_admin`) against the loaded **parent user** inside the generic mounts — so they're already gated to owner-or-admin. The generic *list* mount has no per-parent gate; it would let any authenticated viewer read `/users/{other_id}/saved_searches`. A saved search is private, so the list is hand-written with the same self-or-admin gate the user's clinician related-list (`handle_list_user_clinicians`) uses, and wired through `mount_entity`'s `owned_handlers` in [`../../routes/users.py`](../../routes/users.py).

## Why self-or-admin, not owner-or-admin

This is the first `parent=USER_ENTITY` owned subentity. The framework runs `write_authz` against the parent row — here a `User`, which has no `owner_id`. `OWNER_OR_ADMIN` would read a missing column; the correct rule is `assert_self_or_admin` (`actor.id == user.id` or admin). See the spec docstring.
