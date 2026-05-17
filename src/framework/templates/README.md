# Framework templates: chrome + generic view types

The framework's template root holds the domain-agnostic pieces: the site shell, the cross-resource macro library, and the generic view-type templates that domain pages extend. Nothing here knows what a "user" or "provider" is — it reads context vars and blocks from whichever domain template extends it.

```
src/framework/templates/
├── base.html         ← every page extends this. HTMX setup + primary nav + chrome strips.
├── _shared/          ← cross-resource macros (form fields, table chrome, breadcrumb/toolbar primitives, etc.).
└── views/            ← generic view-type chrome: list, detail, form_new, form_edit.
```

Per-entity templates live in [`../../domain/templates/<entity>/`](../../domain/templates/) and extend a `views/*` template (or `base.html` directly for pages that don't fit the resource grammar, like the `/auth/...` flow).

## Loader

[`../rendering/templating.py`](../rendering/templating.py) wires a Jinja `FileSystemLoader` with two roots:

```python
FileSystemLoader([
    "src/framework/templates",   # base.html, _shared/, views/
    "src/domain/templates",      # per-entity pages
])
```

Names resolve by walking the list, so a domain page can `{% extends "views/list.html" %}` and `{% from "_shared/index_table.html" import index_table %}` without thinking about which directory the referenced template lives in.

## Layering rule

A template under `<resource>/` in either root may only `{% extends %}` / `{% include %}` / `{% from %}` / `{% import %}` from: a root-level file (`base.html`), its own directory, `_shared/`, or `views/`. Cross-cluster references (e.g. `posts/...` from `providers/...`) mean the partial is *de facto* shared and belongs in `_shared/`. Enforced by [`../../../scripts/dev/template_imports_check.py`](../../../scripts/dev/template_imports_check.py) (runs in `dev lint` and pre-commit).

## Generic view-type templates (`views/`)

Each view-type template wires the same three-strip chrome (nav + breadcrumb + toolbar + content) from `base.html` with the breadcrumb and toolbar shape that matches the verb. A child template extending one of these declares only what's unique: a label, a URL, the body markup, and an optional action cluster.

| View type     | Breadcrumb shape                          | Toolbar                                    | Child must declare                                       |
| ------------- | ----------------------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| `list.html`   | `Resource`                                | optional filter widget + actions cluster   | `resource_label`, `content`. Optional: `actions`, `filters`/`filter_action`/`filter_values` (context). |
| `detail.html` | `Resource › <current>`                    | optional actions cluster                   | `resource_label`, `current_label`, `content`, `resource_url` (context). Optional: `actions`. |
| `form_new.html` | `Resource › New`                        | none — form's submit button is the action  | `resource_label`, `content`, `resource_url` (context).   |
| `form_edit.html` | `Resource › <current> › Edit`          | none — form's Save/Cancel buttons are the actions | `resource_label`, `current_label`, `content`, `resource_url`, `resource_detail_url` (context). |

Every view-type template also exposes its `breadcrumb` block for full override, so subresource lists with multi-segment chains (e.g. `Users › <username> › Providers` on `/users/{id}/providers`) keep the chrome by overriding one block while still inheriting the toolbar/content shape.

### Why view-type templates

Before this layer existed, every domain template manually rewired `{% block breadcrumb %}` and `{% block toolbar %}` from `_shared/` macros (`breadcrumb`, `list_toolbar`, `toolbar`). That worked but offered no vocabulary — a reader had to scan 15 lines of imports and block overrides to confirm "this is the list view of providers." `views/list.html` puts that statement in line 1: `{% extends "views/list.html" %}`. The chrome wiring is a property of the view type, not a repeated incantation.

The macros under `_shared/` are still the primitives — `views/*` compose them. A page that needs a chrome shape the view templates don't express (the `/auth/*` flow's centered single-card layout, the post feed's `<ul>` body) extends `base.html` directly or composes the macros by hand.

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

**Breadcrumb zone bar** (`{% block breadcrumb %}`, macro in `_shared/_breadcrumb.html`) renders Pico's native breadcrumb above the toolbar. Every authenticated page extends the block — chrome consistency is the goal. The shape follows the resource hierarchy `list > detail > edit/new`, each level appending one segment:

| Page type        | URL example                    | Breadcrumb                            |
| ---------------- | ------------------------------ | ------------------------------------- |
| Resource list    | `/posts`                       | `Posts`                               |
| Resource detail  | `/posts/{id}`                  | `Posts › Post`                        |
| Resource new     | `/posts/form`                  | `Posts › New`                         |
| Resource edit    | `/posts/{id}/form`             | `Posts › Post › Edit`                 |
| Subresource list | `/users/{id}/providers`        | `Users › <username> › Providers`      |

Every prior segment is a link (`<a href="…">`); the trailing segment is the current page (no `href`, gets `aria-current="page"`). Single-segment list breadcrumbs are still wrapped in the nav so the chrome strip is present and the strip height stays consistent across pages.

Public auth-flow pages (`/auth/login`, `/auth/register`, …) opt out — they aren't in the resource hierarchy.

**Toolbar / action bar** is the zone bar for page-scoped controls. The action cluster is a `<menu>` — HTML's native "list of commands" element — so the page's **primary resource actions** (Edit, Delete, Deactivate/Reactivate, Favorite/Unfavorite) are marked up as the toolbar a screen reader / browser already expects. Each action is a `<li>` child of the menu. Detail pages emit `<menu class="toolbar">` directly (see `_shared/_toolbar.html`); list pages keep a `<div class="toolbar">` outer wrapper with two zones: a search link on the left opening `/<collection>/search`, and the page-action `<menu class="toolbar-right">` (Create, Export...) pushed to the right edge via `margin-left: auto` (see `_shared/list_page.html`). The search link doubles as the active-filter summary: when filters are applied, it reads "Type: Seeking, Description: needle, +2 more filters" (first two inline, the rest collapsed to a tail), with a `Clear all` link sibling that drops every active filter. When no filter is applied, the link simply reads `Search <collection>`. Detail pages compose with the resource's action partial (`_owner_actions.html`, `_admin_actions.html`) or open-coded `<li><button>…</button></li>` items. Pages without page-scoped controls leave the block empty.

Inline / subresource actions inside the page body (per-row delete buttons on `provider/form_edit.html`'s licensure list, inline-add-form submits) are **not** primary resource actions and stay where they are — they act on a single subentity, not on the page's resource.

Edit forms keep a bottom `<a class="secondary outline">Cancel</a>` pointing at the resource's detail page — a deliberate "abandon this edit" affordance.

## Partial convention

Files prefixed with `_` (e.g. `_breadcrumb.html`, `_toolbar.html`, `_provider_row.html`) are partials, `{% include %}`d from full pages — never rendered directly by routes. A partial documents its required context in a `{# ... #}` comment at the top and guards visibility on a single named flag (`{% if can_edit %}`). The handler computes the flag using [`../authz.py`](../authz.py) predicates; partials never introspect `current_user` to decide visibility. Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

## Shared macros (`_shared/`)

- `form_fields.html` — `text_field`, `textarea_field`, `select_field`, `radio_bool_field`, `multi_select_field`, `time_grid_field`, and the schema-driven `field_for`. `<select>` macros iterate over the controlled-vocabulary tuples from [`../../domain/models/enums.py`](../../domain/models/enums.py) and resolve labels from `*_LABELS` — both registered as Jinja globals in [`../rendering/templating.py`](../rendering/templating.py). Adding a value to a tuple flows automatically to every form using these macros.
- `forms.html` — `inline_add_form(...)`: single-fieldset form skeleton for sub-resource add forms.
- `sections.html` — `list_or_empty(...)`: `<ul>` or empty-state. Caller passes the `<li>` body via `{% call(item) %}...{% endcall %}`.
- `actions.html` — `confirm_delete_button(...)`: HTMX `hx-delete` button with confirm dialog.
- `index_table.html` — `index_table(items, headers, row, empty, id=None, row_kwargs={})`: the standard index-page table chrome (`<table role="grid">` with a `<p>` empty state). Headers and rows come from a cluster-local `<resource>/_columns.html` that exports `<resource>_headers()` and `<resource>_row(item, **row_kwargs)`. Every `/<collection>` list page renders through it — see `providers/list.html` for the canonical use. When the cluster's column macros read resource-specific Jinja context (e.g. `LICENSE_TYPES` flowing in via `EntitySpec.static_context`), import them `with context`. Pages with rich empty states (CTAs, per-viewer branches) invoke the macro via `{% call index_table(...) %}<p id="…">…</p>{% endcall %}` and provide their own empty body.
- `_provider_row.html` — `provider_headers()`, `provider_row(provider)`: the provider row shape, shared across `/providers`, `/users/me/favorites`, `/users/{id}/providers`, and the embedded `<section>Providers</section>` on `/users/{id}`. Lives in `_shared/` (not `providers/`) because cross-cluster template imports aren't allowed.
- `list_page.html` — `list_toolbar(...)`: the toolbar shell that `views/list.html` composes. Renders the search link on the left and the right-zone action `<menu>` (caller body is `<li>` items) on the right. The search link does double duty: when no filters are active it reads ``Search <collection>``; when filters are active it summarizes the first two inline and collapses the rest to ``+N more filters``, with a sibling ``Clear all`` link beside it. No separate active-filter strip — the inline summary replaces it. Reads context `handle_list` injects: `active_filters`, `search_url`, `clear_all_url`, `collection_label`.
- `pagination.html` — `pagination(page_meta, paginator_base_query)`: Prev / Page N / Next footer rendered automatically by `views/list.html` after the `{% block content %}`. Reads the `Page` snapshot from [`../dispatch/pagination.py`](../dispatch/pagination.py) (set by `handle_list` and the bespoke list handlers) and emits nothing when the result fits on a single page. `paginator_base_query` is the request's query string with `page=` stripped, so the Prev/Next links round-trip filter state across page navigation.

`index_table` also supports `header_kwargs={}` for headers that vary by page state. Not every list uses the table shape — `/posts` renders a `<ul id="posts-list">` (Pico-default styling, no custom CSS) via `posts/_item.html::post_item(post, active_kind=None)` instead, since the polymorphic kinds need a description-led row (kind chip + lead text + per-chunk metadata) that the table's fixed columns can't express.

The search-page form (`views/search.html`) reads the `Filter` instances declared on the spec; the macro picks the right control by `f.kind` and `f.multi` (search input for `TextFilter`, `<select>` for single-choice, `<input type="checkbox">` grid for multi-choice). `select_field` (for create/edit) is required by default with an optional disabled placeholder.

## Schema-driven `field_for`

`field_for(schema, name, label, current=None, required=None)` in `_shared/form_fields.html` introspects a Pydantic schema via the `field_spec` Jinja global (which points at [`../rendering/form_fields.py`](../rendering/form_fields.py)) to derive:

- `required` — from whether the annotation is `T | None`.
- `<select>` + choices — from `Literal[*TUPLE]`. Labels come from the choice-tuple registry populated in [`../rendering/templating.py`](../rendering/templating.py).
- `pattern` / `maxlength` — from any `HtmlPattern` marker attached to an `Annotated[...]` alias in [`../schema_validators.py`](../schema_validators.py).

`field_for` does not yet handle multi-select, checkbox grids, or radio-bool — those have form-level grouping the existing macros own and a schema-side shape (e.g. `list[Literal]`) that isn't yet a stable signal for which control to render. Hand-rolled `text_field` / `select_field` calls remain appropriate when the form intentionally diverges from the schema.

## Template context

Handlers pass only resource-specific data. Chrome scalars (`is_authenticated`, `is_admin`, `current_username`, `current_user_id`) and dev globals are merged in by `APIResponse.html_response` — handlers never compute or pass them. See [`../http/responses.py`](../http/responses.py).

## Tests

- `test_views.py` (colocated): renders each view-type template via stub child templates and pins the breadcrumb / toolbar / content contract. A regression in the chrome wiring is caught here even before any domain page is changed.
- Per-entity rendering is exercised indirectly via route tests under [`../../domain/routes/`](../../domain/routes/). When adding a template, extend the relevant route test (or add one) to cover its rendering. Selectors must scope to a stable handle (`id`, `class`, `data-testid`) rather than relying on a page having only one `<ul>` / `<form>` / `<table>` — see [`../../../tests/README.md`](../../../tests/README.md).
