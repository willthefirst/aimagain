# Posts templates

Jinja templates for the post CRUD flows. HTMX-driven; forms submit JSON via `hx-ext="json-enc"`.

## Files

- `list.html` — listing page (`GET /posts`). Shows newest-first; links to per-post detail and the create form.
- `detail.html` — single-post read view (`GET /posts/{id}`). Includes `_owner_actions.html`.
- `new.html` — create form (`GET /posts/form` → `POST /posts`).
- `edit.html` — edit form (`GET /posts/{id}/form` → `PATCH /posts/{id}`).
- `_owner_actions.html` — partial showing Edit/Delete actions for owners and admins.

## Parent / per-kind detail

`Post` is split into a parent row (id, kind, owner, timestamps) and a per-kind detail row. Today the only kind is `note`, with `title` and `body` on `post.note_detail`.

Templates dereference through the relationship: `{{ post.note_detail.title }}`, `{{ post.note_detail.body }}`. Don't reach for `post.title` — it isn't there. The `note_detail` relationship is eager-loaded (`lazy="selectin"`) so accessing it from a template is safe.

When a future kind ships, this layer will gain per-kind partials (e.g. `_note_body.html`, `_referral_body.html`) selected on `post.kind`. Until then, all post templates assume `kind == 'note'` and dereference `note_detail` directly.
