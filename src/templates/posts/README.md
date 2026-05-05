# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit JSON via `hx-ext="json-enc"`.

## Files

- `list.html` — listing page (`GET /posts`). Shows newest-first; branches on `post.kind` to render a kind-appropriate row label. The "New X" links at the top are rendered from `post_kinds` (a list of `KindSpec` from [`src/models/post_kinds.py`](../../models/post_kinds.py), passed in by `handle_list_posts`), so adding a registered kind automatically adds its create-form link.
- `detail.html` — single-post read view (`GET /posts/{id}`). Branches on `post.kind` to render the right detail block. Includes `_owner_actions.html`.
- `new.html` — create form for `kind='note'` (`GET /posts/form` → `POST /posts`).
- `new_client_referral.html` — create form for `kind='client_referral'`. Submits a hidden `kind` field.
- `new_provider_availability.html` — create form for `kind='provider_availability'`. Submits a hidden `kind` field.
- `edit.html` — edit form for `kind='note'` (`GET /posts/{id}/form` → `PATCH /posts/{id}`). The route layer picks the template from `post.kind`.
- `edit_client_referral.html` — edit form for `kind='client_referral'`. Same wiring, different fields.
- `edit_provider_availability.html` — edit form for `kind='provider_availability'`. Same wiring, different fields.
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins; kind-agnostic.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Kinds today: `note` (`post.note_detail` → title + body), `client_referral` (`post.client_referral_detail` → description), `provider_availability` (`post.provider_availability_detail` → practice_name). The two non-note kinds are MVP shape — full intake forms per [`notes/forms_spec.md`](../../../notes/forms_spec.md) follow.

Templates dereference through the right relationship per branch: `{{ post.note_detail.title }}` inside a `kind == "note"` block, `{{ post.client_referral_detail.description }}` inside a `kind == "client_referral"` block, `{{ post.provider_availability_detail.practice_name }}` inside a `kind == "provider_availability"` block. Don't reach for `post.title` — it isn't there. Detail relationships are eager-loaded (`lazy="selectin"`) so accessing them from a template is safe.

When a new kind ships:

1. Add `posts/new_<kind>.html` and `posts/edit_<kind>.html`. Register their paths on the kind's `KindSpec` in [`src/models/post_kinds.py`](../../models/post_kinds.py); the route layer reads `spec.create_template` / `spec.edit_template` from there.
2. Add a `{% elif post.kind == "<kind>" %}` branch in `list.html` and `detail.html` for the per-kind body rendering. (The "New X" link in `list.html` follows automatically via the registry-driven loop.)
