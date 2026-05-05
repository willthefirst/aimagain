# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit JSON via `hx-ext="json-enc"`.

## Files

- `list.html` — listing page (`GET /posts`). Shows newest-first; branches on `post.kind` to render a kind-appropriate row label. Links to every per-kind create form (`/posts/form?kind=client_referral`, `/posts/form?kind=provider_availability`).
- `detail.html` — single-post read view (`GET /posts/{id}`). Branches on `post.kind` to render the right detail block. Includes `_owner_actions.html`.
- `new_client_referral.html` — create form for `kind='client_referral'`. Submits a hidden `kind` field.
- `new_provider_availability.html` — create form for `kind='provider_availability'`. Submits a hidden `kind` field.
- `edit_client_referral.html` — edit form for `kind='client_referral'`. The route layer picks the template from `post.kind`.
- `edit_provider_availability.html` — edit form for `kind='provider_availability'`. Same wiring, different fields.
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins; kind-agnostic.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Kinds today: `client_referral` (`post.client_referral_detail` → description) and `provider_availability` (`post.provider_availability_detail` → practice_name). Both are MVP shape — full intake forms per [`notes/forms_spec.md`](../../../notes/forms_spec.md) follow.

Templates dereference through the right relationship per branch: `{{ post.client_referral_detail.description }}` inside a `kind == "client_referral"` block, `{{ post.provider_availability_detail.practice_name }}` inside a `kind == "provider_availability"` block. Don't reach for `post.title` — it isn't there. Detail relationships are eager-loaded (`lazy="selectin"`) so accessing them from a template is safe.

When a new kind ships:

1. Add `posts/new_<kind>.html` and register it in `_CREATE_FORM_TEMPLATES` in [`src/api/routes/posts.py`](../../api/routes/posts.py).
2. Add `posts/edit_<kind>.html` and register it in `_EDIT_FORM_TEMPLATES`.
3. Add a `{% elif post.kind == "<kind>" %}` branch in `list.html` and `detail.html`.
