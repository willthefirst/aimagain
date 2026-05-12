# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit form-encoded data via `hx-{post,patch}` (see [`_client_referral_form.html`](_client_referral_form.html) / [`_provider_availability_form.html`](_provider_availability_form.html)). Multi-checkbox fields (`desired_times`, `services`, `settings`) are normalized on the wire schema by `_scalar_to_list` in [`src/domain/logic/posts/schema.py`](../../logic/posts/schema.py).

## Files

- `list.html` — listing page (`GET /posts`). Newest-first; branches on `post.kind` to render a kind-appropriate row label. The "New X" links at the top are rendered from `post_kinds` (a list of `PostKindSpec` from [`src/domain/models/posts/post_kinds.py`](../../models/posts/post_kinds.py), passed in by `handle_list_posts`), so adding a registered kind automatically adds its create-form link.
- `detail.html` — single-post read view (`GET /posts/{id}`). Branches on `post.kind` to render the right detail block. Includes `_owner_actions.html`.
- `_client_referral_form.html` / `_provider_availability_form.html` — per-kind form-body macros. Each takes `(hx_method, action, submit_label, post=None)` and renders the full intake form using the shared field-render macros from [`../_shared/form_fields.html`](../_shared/form_fields.html). Field order, section grouping, labels, and required/optional state live here in one place per kind.
- `new_<kind>.html` — create-form page; ~5-line wrapper that imports the per-kind form macro and calls it with `hx_method="post"`, `action="/posts"`.
- `edit_<kind>.html` — edit-form page; same wrapper pattern with `hx_method="patch"`, `action="/posts/{id}"`, and `post=post` for prefill.
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins; kind-agnostic.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Kinds today: `client_referral` (`post.client_referral_detail`) and `provider_availability` (`post.provider_availability_detail`). Both carry the scalar (single-value) fields from their intake forms plus the `desired_times` (7×3 grid) and `services` (5-checkbox) multi-selects, both stored as JSON. CR's `services` is optional; PA's is required-min-1. PA also carries the `settings` (5-checkbox) multi-select (required-min-1).

Templates dereference through the right relationship per branch: `{{ d.description }}` after `{% set d = post.client_referral_detail %}` inside a `kind == "client_referral"` block, etc. Don't reach for `post.title` — it isn't there. Detail relationships are eager-loaded (`lazy="selectin"`) so accessing them from a template is safe.

## When a new kind ships

1. Add the per-kind form-body partial `posts/_<kind>_form.html` (a `{% macro %}` taking `(hx_method, action, submit_label, post=None)`) using the shared field-render macros in [`../_shared/form_fields.html`](../_shared/form_fields.html).
2. Add `posts/new_<kind>.html` and `posts/edit_<kind>.html` as ~5-line wrappers around the form macro. Register their paths on the kind's `PostKindSpec` in [`src/domain/models/posts/post_kinds.py`](../../models/posts/post_kinds.py); the route layer reads `spec.create_template` / `spec.edit_template` from there.
3. Add a `{% elif post.kind == "<kind>" %}` branch in `list.html` and `detail.html` for the per-kind row label and read-view body. (The "New X" link in `list.html` follows automatically via the registry-driven loop.)
4. If the kind introduces a new controlled-vocabulary, add the tuple + `*_LABELS` dict to `src/domain/models/enums.py` and register both as Jinja globals in `src/framework/templating.py`. The shared `select_field` macro then renders dropdowns from them with no further per-template work.
