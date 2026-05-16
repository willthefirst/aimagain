# Templates

Jinja2, server-rendered, htmx for progressive enhancement. One cluster directory per resource.

- `base.html` — every page extends this. HTMX setup + site-wide nav.
- `_shared/` — cross-resource macros (see below).
- `<resource>/` — that resource's templates. Cluster-local partials are prefixed `_`.

## Layering rule

A template under `<resource>/` may only `{% extends %}` / `{% include %}` / `{% from %}` / `{% import %}` from: the project root (`base.html`), its own directory, or `_shared/`. Anything else means the partial is *de facto* shared and belongs in `_shared/`. Enforced by [`../../../scripts/dev/template_imports_check.py`](../../../scripts/dev/template_imports_check.py) (runs in `dev lint` and pre-commit).

## Partial convention

Files prefixed with `_` are shared partials, `{% include %}`d from full pages — never rendered directly by routes. A partial documents its required context in a `{# ... #}` comment at the top and guards visibility on a single named flag (`{% if can_edit %}`). The handler computes the flag using [`../../framework/authz.py`](../../framework/authz.py) predicates; partials never introspect `current_user` to decide visibility. Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

## Shared macros (`_shared/`)

- `form_fields.html` — `text_field`, `textarea_field`, `select_field`, `radio_bool_field`, `multi_select_field`, `time_grid_field`, and the schema-driven `field_for`. `<select>` macros iterate over the controlled-vocabulary tuples from [`../models/enums.py`](../models/enums.py) and resolve labels from `*_LABELS` — both registered as Jinja globals in [`../../framework/rendering/templating.py`](../../framework/rendering/templating.py). Adding a value to a tuple flows automatically to every form using these macros.
- `forms.html` — `inline_add_form(...)`: single-fieldset form skeleton for sub-resource add forms.
- `sections.html` — `list_or_empty(...)`: `<ul>` or empty-state. Caller passes the `<li>` body via `{% call(item) %}...{% endcall %}`.
- `actions.html` — `confirm_delete_button(...)`: HTMX `hx-delete` button with confirm dialog.
- `index_table.html` — `index_table(items, headers, row, empty, id=None, row_kwargs={})`: the standard index-page table chrome (wrapping `<div class="index-table">`, `<table role="grid">`, empty-state `<p class="index-empty">`). The wrapper owns mobile-overflow: a site-wide `overflow-x: auto` in `base.html` scrolls a wide table inside its container instead of pushing the viewport wide, so list pages on a phone show a scroll-affordance rather than breaking layout. Headers and rows come from a cluster-local `<resource>/_columns.html` that exports `<resource>_headers()` and `<resource>_row(item, **row_kwargs)`. Every `/<collection>` list page renders through it — see `providers/list.html` for the canonical use. When the cluster's column macros read resource-specific Jinja context (e.g. `LICENSE_TYPES` flowing in via `EntitySpec.static_context`), import them `with context`. Pages with rich empty states (CTAs, per-viewer branches) invoke the macro via `{% call index_table(...) %}<p class="index-empty">…</p>{% endcall %}` and provide their own empty body.
- `index_filters.html` — `index_filters(filters, action, values)`: filter form for an index page. Reads the `filters` tuple `handle_list` echoes into context (`Filter` instances declared on `EntitySpec.filters`; see [`../../framework/dispatch/filters.py`](../../framework/dispatch/filters.py)) and renders one control per filter (`<input type="search">` for `TextFilter`, `<select>` / `<select multiple>` for `ChoiceFilter`) inside a `<fieldset><legend>Filter</legend>` with Apply + Clear buttons. Plain `<form method="get">` — no JS, no progressive add/remove chrome. Every declared filter is always visible; users fill the ones they want and ignore the rest. Live today on `/posts`; the other list pages still use the legacy single-`QueryParam` shape and migrate when their filter set grows.
- `_provider_row.html` — `provider_headers()`, `provider_row(provider)`: the provider row shape, shared across `/providers`, `/users/me/favorites`, `/users/{id}/providers`, and the embedded `<section>Providers</section>` on `/users/{id}`. Lives in `_shared/` (not `providers/`) because cross-cluster template imports aren't allowed; provider-specific filter form stays in `providers/_columns.html` since only the /providers index uses it.

## Page chrome contract

Every page extending `base.html` lands the same three-strip chrome above its content. From top to bottom:

```
┌───────────────────────────────────────────────────────────┐
│ <header> primary nav        brand + auth-aware right slot │  ← `base.html`
├───────────────────────────────────────────────────────────┤
│ breadcrumb zone bar          Resource › … › Current        │  ← `{% block breadcrumb %}` (detail/form pages only)
├───────────────────────────────────────────────────────────┤
│ toolbar / action bar         [filters left]    [actions ▶] │  ← `{% block toolbar %}`
├───────────────────────────────────────────────────────────┤
│ page content                                              │  ← `{% block content %}`
└───────────────────────────────────────────────────────────┘
```

**Primary nav** lives in `base.html` and renders on every screen (authed *and* anonymous). Its right-side slot (`#primary-nav`) swaps the profile icon for a Login link depending on `is_authenticated`. Pages don't extend it.

**Breadcrumb zone bar** (`{% block breadcrumb %}`, macro in `_shared/_breadcrumb.html`) renders Pico's native breadcrumb above the toolbar. Pages opt in by extending the block; otherwise it's invisible. The shape follows the resource hierarchy `list > detail > edit/new`:

| Page type        | URL example              | Breadcrumb                    |
| ---------------- | ------------------------ | ----------------------------- |
| Resource list    | `/posts`                 | *(none — root of hierarchy)*  |
| Resource detail  | `/posts/{id}`            | `Posts › Post`                |
| Resource new     | `/posts/form`            | `Posts › New`                 |
| Resource edit    | `/posts/{id}/form`       | `Posts › Post › Edit`         |

The leading segment is the resource label linked to its list page; the trailing segment is the current page (no `href`, gets `aria-current="page"`). Subresource list pages (`/users/{id}/providers`) are still list pages and stay breadcrumb-less.

**Toolbar / action bar** is the zone bar for page-scoped controls. See `_shared/_toolbar.html` for the two-zone layout (`.toolbar-left` fills the row for filters; `.toolbar-right` parks page actions on the right; single-action toolbars right-align without wrappers). The toolbar is the single home for the page's **primary resource actions**: Edit, Delete, Deactivate/Reactivate, Favorite/Unfavorite. List pages compose the toolbar with `index_filters(...)` in the left zone and a Create-resource action in the right zone; detail pages compose it with the resource's action partial (`_owner_actions.html`, `_admin_actions.html`) or open-coded buttons. Pages without page-scoped controls leave the block empty.

Inline / subresource actions inside the page body (per-row delete buttons on `provider/form_edit.html`'s licensure list, inline-add-form submits) are **not** primary resource actions and stay where they are — they act on a single subentity, not on the page's resource.

Edit forms keep a bottom `<a class="secondary outline">Cancel</a>` pointing at the resource's detail page — a deliberate "abandon this edit" affordance.

`index_table` also supports `header_kwargs={}` for headers that vary by page state. Not every list uses the table shape — `/posts` renders a `<ul id="posts-list">` (Pico-default styling, no custom CSS) via `posts/_item.html::post_item(post, active_kind=None)` instead, since the polymorphic kinds need a description-led row (kind chip + lead text + per-chunk metadata) that the table's fixed columns can't express.

List-page filter controls render through `_shared/index_filters.html` (one `_filter_control` macro per declared `Filter` instance on the spec). `select_field` (for create/edit) is required by default with an optional disabled placeholder.

## Schema-driven `field_for`

`field_for(schema, name, label, current=None, required=None)` in `_shared/form_fields.html` introspects a Pydantic schema via the `field_spec` Jinja global (which points at [`../../framework/rendering/form_fields.py`](../../framework/rendering/form_fields.py)) to derive:

- `required` — from whether the annotation is `T | None`.
- `<select>` + choices — from `Literal[*TUPLE]`. Labels come from the choice-tuple registry populated in [`../../framework/rendering/templating.py`](../../framework/rendering/templating.py).
- `pattern` / `maxlength` — from any `HtmlPattern` marker attached to an `Annotated[...]` alias in [`../../framework/schema_validators.py`](../../framework/schema_validators.py).

`field_for` does not yet handle multi-select, checkbox grids, or radio-bool — those have form-level grouping the existing macros own and a schema-side shape (e.g. `list[Literal]`) that isn't yet a stable signal for which control to render. Hand-rolled `text_field` / `select_field` calls remain appropriate when the form intentionally diverges from the schema.

## Per-kind form partials

Resources with polymorphic intake forms follow a two-layer pattern within their cluster: `_<variant>_form.html` defines a form-body `{% macro %}` taking `(hx_method, action, submit_label, prefill=None)`; `new_<variant>.html` and `edit_<variant>.html` are ~5-line wrappers that call it. See the cluster's own README when this pattern is in use (e.g. [`posts/README.md`](posts/README.md)).

## Template context

Handlers pass only resource-specific data. Chrome scalars (`is_authenticated`, `is_admin`, `current_username`, `current_user_id`) and dev globals are merged in by `APIResponse.html_response` — handlers never compute or pass them. See [`../../framework/http/responses.py`](../../framework/http/responses.py).

## Tests

Exercised indirectly via route tests under [`../routes/`](../routes/). When adding a template, extend the relevant route test (or add one) to cover its rendering. Selectors must scope to a stable handle (`id`, `class`, `data-testid`) rather than relying on a page having only one `<ul>` / `<form>` / `<table>` — see [`../../../tests/README.md`](../../../tests/README.md).
