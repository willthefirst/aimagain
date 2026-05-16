# Domain templates

Per-entity Jinja templates. One cluster directory per resource (`providers/`, `users/`, `posts/`, `favorites/`, `auth/`); cluster-local partials are prefixed `_`.

Chrome, shared macros, and the generic view-type templates live in [`../../framework/templates/`](../../framework/templates/) — see its README for the full contract, including the page-chrome strips, the layering rule, and the four view-type templates (`views/list.html`, `views/detail.html`, `views/form_new.html`, `views/form_edit.html`) that this directory's pages extend.

## Per-cluster grammar

A resource cluster `<entity>/` typically contains:

- `list.html` — extends `views/list.html`. Declares `resource_label`, optional `filters` / `filter_action` / `filter_values`, and a `content` block (the table or list body).
- `detail.html` — extends `views/detail.html`. Declares `resource_label`, `current_label`, `resource_url`, optional `actions`, and `content`.
- `form_new.html` — extends `views/form_new.html`. Declares `resource_label`, `resource_url`, and the form body in `content`.
- `form_edit.html` — extends `views/form_edit.html`. Declares `resource_label`, `current_label`, `resource_url`, `resource_detail_url`, and the form body in `content`.
- `_columns.html` (cluster-local partial) — `<entity>_headers()` / `<entity>_row(item, **row_kwargs)` macros consumed by `_shared/index_table.html` from the list page. Lives in the cluster (rather than `_shared/`) when only the entity's own list uses it.
- `_<role>_actions.html` (cluster-local partial) — owner/admin action button clusters for the entity, `{% include %}`d from the detail page's `actions` block.

Subresource lists (e.g. `/users/{id}/providers`) override `{% block breadcrumb %}` to land a multi-segment chain (`Users › <username> › Providers`) while still inheriting the list view's toolbar + content shape from `views/list.html`. See `users/providers_list.html`.

Pages that don't fit the resource grammar — the `/auth/*` flow's centered single-card layout, the `/posts/*` polymorphic create/edit forms — extend `base.html` directly and compose the `_shared/` macros by hand. See [`posts/README.md`](posts/README.md) for the two-layer `_<variant>_form.html` + `new_<variant>.html` pattern used for polymorphic intake.

## Schema-driven `field_for`

Form templates use `field_for(schema, name, label)` from [`../../framework/templates/_shared/form_fields.html`](../../framework/templates/_shared/form_fields.html) to derive each `<input>`'s attributes from the Pydantic schema. See the framework README for details — adding a value to a controlled-vocabulary tuple in [`../models/enums.py`](../models/enums.py) flows automatically to every form using these macros.

## Tests

Exercised indirectly via route tests under [`../routes/`](../routes/). When adding a template, extend the relevant route test (or add one) to cover its rendering. Selectors must scope to a stable handle (`id`, `class`, `data-testid`) rather than relying on a page having only one `<ul>` / `<form>` / `<table>` — see [`../../../tests/README.md`](../../../tests/README.md).
