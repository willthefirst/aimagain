# Domain templates

Per-entity Jinja templates. One cluster directory per resource (`providers/`, `users/`, `posts/`, `favorites/`, `auth/`); cluster-local partials are prefixed `_`.

Chrome, shared macros, and the generic view-type templates live in [`../../framework/templates/`](../../framework/templates/) — see its README for the full contract, including the page-chrome strips, the layering rule, and the four view-type templates (`views/list.html`, `views/detail.html`, `views/form_new.html`, `views/form_edit.html`) that this directory's pages extend.

## Per-cluster grammar

A resource cluster `<entity>/` typically contains:

- `list.html` — extends `views/list.html`. Declares `resource_label`, an optional `actions` block (right-aligned toolbar items, each an `<li>` inside `<menu class="toolbar-right">`), and a `content` block (the table or list body). The toolbar's filter link is rendered automatically by `views/list.html` from spec-driven context (`active_filters`, `search_url`) that `handle_list` injects — no per-template wiring needed.
- `search.html` — extends `views/search.html`. One-line stub setting the `resource_label` breadcrumb for entities that opt into `routes.search=True`. Renders one form control per declared secondary `Filter` on the spec.
- `detail.html` — extends `views/detail.html`. Declares `resource_label`, `current_label`, `resource_url`, optional `actions`, and `content`.
- `form_new.html` — extends `views/form_new.html`. Declares `resource_label`, `resource_url`, and the form body in `content`.
- `form_edit.html` — extends `views/form_edit.html`. Declares `resource_label`, `current_label`, `resource_url`, `resource_detail_url`, and the form body in `content`.
- `_columns.html` (cluster-local partial) — `<entity>_headers()` / `<entity>_row(item, **row_kwargs)` macros consumed by `_shared/index_table.html` from the list page. Lives in the cluster (rather than `_shared/`) when only the entity's own list uses it.
- `_<role>_actions.html` (cluster-local partial) — owner/admin action button clusters for the entity, `{% include %}`d from the detail page's `actions` block.

Subresource lists (e.g. `/users/{id}/clinicians`) override `{% block breadcrumb %}` to land a multi-segment chain (`Users › <username> › Clinicians`) while still inheriting the list view's toolbar + content shape from `views/list.html`. See `users/providers_list.html` (file name retained — the directory cluster is still `providers/` because the model class is `Provider`; only the user-facing surface flipped in #642 PR 4).

Pages that don't fit the resource grammar — the `/auth/*` flow's centered single-card layout — extend `base.html` directly and compose the `_shared/` macros by hand.

The two post URL families have different template shapes:

- **`referrals/`** (kind-locked leaf, `kind='referral'`): carries `list.html`, `detail.html`, `form_new.html`, `form_edit.html`, `search.html`, and `_form.html` (the create/edit form-body macro).
- **`openings/`** (subset-supertype over `clinician_opening` + `program_intake`): carries `list.html`, `detail.html`, `search.html`, and *per-subkind* form templates — `new_<kind>.html` / `edit_<kind>.html` / `_form_<kind>.html` for each subkind. The handler sets `template_name = POST_KINDS[kind].create_template` (or `edit_template`) to pick the right form by the `?kind=` URL param or the row's stored kind. The `form_new.html` / `form_edit.html` files at the top of the directory are spec-default fallbacks (picker for `form_new`, kind-dispatching include for `form_edit`).

The shared post-card partials (`_item`, `_facts_block`, `_how_to_refer`, `_modality_chips`, `_owner_actions`) live in [`_shared/posts/`](_shared/posts/) and are imported by both families' list and detail pages — see #628. The services list is the first row of `_facts_block`'s `<dl>` rather than its own partial.

The auth-flow pages (`auth/login.html`, `auth/register.html`, `auth/forgot_password.html`, `auth/reset_password.html`) each render a single `<article class="auth-page">` card. The `.auth-page` rule in [`../../framework/templates/base.html`](../../framework/templates/base.html) caps the card at 28rem and centers it horizontally — without the class the card stretches to the full `<main class="container">` width on tablet/desktop.

## Tests

Exercised indirectly via route tests under [`../routes/`](../routes/). Selector and fixture conventions live in [`../../../tests/README.md`](../../../tests/README.md).
