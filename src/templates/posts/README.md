# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit JSON via `hx-ext="json-enc-arrays"` (a small extension defined in `base.html` that wraps htmx's `json-enc` and adds always-array semantics: a form declares `data-array-fields="<name> ..."` and those names always serialize as JSON arrays — `[]` / `[x]` / `[x,y]` for 0/1/2+ checked controls — instead of collapsing 0/1 controls to absent/scalar).

## Files

- `list.html` — listing page (`GET /posts`). Newest-first; branches on `post.kind` to render a kind-appropriate row label. The "New X" links at the top are rendered from `post_kinds` (a list of `KindSpec` from [`src/models/post_kinds.py`](../../models/post_kinds.py), passed in by `handle_list_posts`), so adding a registered kind automatically adds its create-form link.
- `detail.html` — single-post read view (`GET /posts/{id}`). Branches on `post.kind` to render the right detail block. Includes `_owner_actions.html`.
- `_form_macros.html` — shared field-render macros (`text_field`, `textarea_field`, `select_field`, `radio_bool_field`, `time_grid_field`). Used by the per-kind form partials below. The `<select>` macro iterates over a controlled-vocabulary tuple from [`src/models/post_enums.py`](../../models/post_enums.py) (registered as Jinja globals in [`src/core/templating.py`](../../core/templating.py)) and looks display labels up in a sibling `*_LABELS` dict. The `time_grid_field` macro renders a 7×3 day-of-week × part-of-day checkbox grid that all share the same `name`; the `json-enc-arrays` HTMX extension (in `base.html`) serializes the checked values as a single JSON array.
- `_client_referral_form.html` / `_provider_availability_form.html` — per-kind form-body macros. Each takes `(hx_method, action, submit_label, post=None)` and renders the full intake form (per [`notes/forms_spec.md`](../../../notes/forms_spec.md)) using the shared macros. Field order, section grouping, labels, and required/optional state live here in one place per kind.
- `new_<kind>.html` — create-form page; ~5-line wrapper that imports the per-kind form macro and calls it with `hx_method="post"`, `action="/posts"`.
- `edit_<kind>.html` — edit-form page; same wrapper pattern with `hx_method="patch"`, `action="/posts/{id}"`, and `post=post` for prefill.
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins; kind-agnostic.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Kinds today: `client_referral` (`post.client_referral_detail`) and `provider_availability` (`post.provider_availability_detail`). Both carry the scalar (single-value) fields from the intake forms in [`notes/forms_spec.md`](../../../notes/forms_spec.md) plus the `desired_times` multi-select (rendered with `time_grid_field`, stored as JSON). The remaining multi-select fields (`services`, `settings`) follow in a separate change.

Templates dereference through the right relationship per branch: `{{ d.description }}` after `{% set d = post.client_referral_detail %}` inside a `kind == "client_referral"` block, etc. Don't reach for `post.title` — it isn't there. Detail relationships are eager-loaded (`lazy="selectin"`) so accessing them from a template is safe.

## When a new kind ships

1. Add the per-kind form-body partial `posts/_<kind>_form.html` (a `{% macro %}` taking `(hx_method, action, submit_label, post=None)`) using the shared `_form_macros.html` macros.
2. Add `posts/new_<kind>.html` and `posts/edit_<kind>.html` as ~5-line wrappers around the form macro. Register their paths on the kind's `KindSpec` in [`src/models/post_kinds.py`](../../models/post_kinds.py); the route layer reads `spec.create_template` / `spec.edit_template` from there.
3. Add a `{% elif post.kind == "<kind>" %}` branch in `list.html` and `detail.html` for the per-kind row label and read-view body. (The "New X" link in `list.html` follows automatically via the registry-driven loop.)
4. If the kind introduces a new controlled-vocabulary, add the tuple + `*_LABELS` dict to `src/models/post_enums.py` and register both as Jinja globals in `src/core/templating.py`. The shared `select_field` macro then renders dropdowns from them with no further per-template work.
