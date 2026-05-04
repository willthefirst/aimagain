# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit JSON via `hx-ext="json-enc"`.

## Files

- `list.html` — listing page (`GET /posts`). Shows newest-first; branches on `post.kind` to render a kind-appropriate row label. Links to both per-kind create forms (`/posts/form` and `/posts/form?kind=client_referral`).
- `detail.html` — single-post read view (`GET /posts/{id}`). Branches on `post.kind` to render the right detail block. Includes `_owner_actions.html`.
- `new.html` — create form for `kind='note'` (`GET /posts/form` → `POST /posts`).
- `new_client_referral.html` — create form for `kind='client_referral'` (`GET /posts/form?kind=client_referral` → `POST /posts`). Submits a hidden `kind` field.
- `edit.html` — edit form for `kind='note'` (`GET /posts/{id}/form` → `PATCH /posts/{id}`). The route layer picks the template from `post.kind`.
- `edit_client_referral.html` — edit form for `kind='client_referral'`. Same wiring as `edit.html`, different fields.
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins; kind-agnostic.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Kinds today: `note` (`post.note_detail` → title + body) and `client_referral` (`post.client_referral_detail` → description; MVP shape, full intake form per [`notes/forms_spec.md`](../../../notes/forms_spec.md) follows).

Templates dereference through the right relationship per branch: `{{ post.note_detail.title }}` inside a `kind == "note"` block, `{{ post.client_referral_detail.description }}` inside a `kind == "client_referral"` block. Don't reach for `post.title` — it isn't there. Detail relationships are eager-loaded (`lazy="selectin"`) so accessing them from a template is safe.

When a new kind ships:

1. Add `posts/new_<kind>.html` and register it in `_CREATE_FORM_TEMPLATES` in [`src/api/routes/posts.py`](../../api/routes/posts.py).
2. Add `posts/edit_<kind>.html` and register it in `_EDIT_FORM_TEMPLATES`.
3. Add a `{% elif post.kind == "<kind>" %}` branch in `list.html` and `detail.html`.
