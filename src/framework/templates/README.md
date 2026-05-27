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

| View type     | Breadcrumb back target                    | Toolbar                                    | Child must declare                                       |
| ------------- | ----------------------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| `list.html`   | _(none — list pages omit the breadcrumb)_ | optional filter widget + actions cluster   | `resource_label`, `content`. Optional: `actions`, `filters`/`filter_action`/`filter_values` (context). |
| `detail.html` | `← Resource`                              | optional actions cluster                   | `resource_label`, `current_label`, `content`, `resource_url` (context). Optional: `actions`. |
| `form_new.html` | `← Resource`                            | none — form's submit button is the action  | `resource_label`, `content`, `resource_url` (context). H1 = `create_heading`, sourced from `entity_create_label(spec.name, kind=...)` via the form handler — children don't override the H1. |
| `form_edit.html` | `← <current>`                          | none — form's Save/Cancel buttons are the actions | `resource_label`, `current_label`, `content`, `resource_url`, `resource_detail_url` (context). `current_label` is the **specific resource being edited** (e.g. `{{ organization.name }}`, `{{ view.headline }}`) — not a generic kind noun. |
| `search.html` | `← Resource`                              | none — form's submit button is the action  | `resource_label` (context). H1 = `filter_heading`, sourced from `entity_filter_label(spec.name)` via the search handler. |

The breadcrumb is always a single back affordance — a left chevron + the deepest clickable parent's label — at every viewport. The macro picks the back target by walking the chain backward to the last item with a non-`None` href, so a child template can override `{% block breadcrumb %}` with a multi-item chain (e.g. `[("Users", …), (username, /users/<id>), ("Clinicians", None)]` on `/users/{id}/clinicians`) to shift the back link one level up the tree without changing the visible shape.

### Create / filter labels — single source of truth

Every "Create X" string in the app (the form-page H1, the toolbar Create button, the chrome nav CTA, the polymorphic kind-picker options) and every "Filter X" string (the toolbar Filter link, the dedicated search-page H1) funnels through the helpers in [`../rendering/labels.py`](../rendering/labels.py). Templates call the Jinja-global form (`{{ entity_create_label('opening') }}`, `{{ entity_filter_label('clinician') }}`); the framework's `handle_get_new_form` / `mount_search` / `handle_list` handlers call the spec-direct form (`create_label_for(spec, kind=...)`, `filter_label_for(spec)`) to populate `create_heading` / `filter_heading` in template context. Because both surfaces go through the same function, the button that opens a form and the H1 the user lands on cannot drift — pinned by `framework/rendering/test_labels.py`.

The "Create X" noun resolves to: per-kind `list_label` from the discriminator registry when a polymorphic spec is in play (`Create clinician opening`, `Create program intake`, `Create client referral`), otherwise the spec's `singular_label` (which defaults to `name` — `Create organization`, `Create clinician`, `Create program`). The "Filter X" plural is always the spec's `url_collection` (`Filter clinicians`, `Filter openings`).

### Why view-type templates

Before this layer existed, every domain template manually rewired `{% block breadcrumb %}` and `{% block toolbar %}` from `_shared/` macros (`breadcrumb`, `page_toolbar`). That worked but offered no vocabulary — a reader had to scan 15 lines of imports and block overrides to confirm "this is the list view of providers." `views/list.html` puts that statement in line 1: `{% extends "views/list.html" %}`. The chrome wiring is a property of the view type, not a repeated incantation.

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
├───────────────────────────────────────────────────────────┤
│ <footer> site chrome           &copy; … · support@ …      │  ← `{% block footer %}` (default body in `base.html`)
└───────────────────────────────────────────────────────────┘
```

**Body layout.** `<header>`, `<main>`, and `<footer>` are direct siblings of `<body>`, and `<body>` is a three-row CSS grid (`grid-template-rows: auto 1fr auto`) sized to `min-height: 100dvh`. Short pages pin the footer to the viewport bottom instead of leaving it floating; tall pages flow normally and push the footer below. The landing page reuses this scaffold to vertically center its hero inside the `<main>` row (see [`../../domain/templates/landing.html`](../../domain/templates/landing.html)).

**Site footer** (`{% block footer %}`) renders on every page from the default body in `base.html` — a centered `<small>` with the copyright line and a `mailto:` to support. Pages can override the block to swap or extend the line; today none do.

**Primary nav** lives in `base.html` and renders on every screen (authed *and* anonymous) as a single `<ul id="primary-nav">`. The brand sits on the left; when authed, four inline links push to the right via `margin-left: auto` on the first link: Referrals (`/referrals`), Openings (`/openings`), Profile (`/users/me`), and Sign out (an `<a hx-post="/auth/sign-out">` — the route returns `HX-Redirect`). Anonymous visitors see only the brand; the chrome carries no Login shortcut (visitors enter the auth flow from the landing page CTA). Active state is matched against `request.url.path`. Pages don't extend it.

The active tab carries `aria-current="page"` plus `class="contrast"`, and `base.html` styles `nav[aria-label="Primary"] a[aria-current="page"]` with a bottom underline + font-weight bump so the section reads at a glance — Pico's default `aria-current` tint alone was too subtle (#589). The rule scopes to the primary nav so breadcrumb / pagination links that also set `aria-current` keep their lighter treatment. Subpaths under each URL family (e.g. `/openings/{id}`, `/openings/form?kind=clinician_opening`) light the parent section tab. `test_views.py` pins the URL → active-tab mapping, and `test_primary_nav_omits_login_link_for_anonymous_visitors` pins the no-Login contract across every anonymous-accessible URL family.

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

**Toolbar / action bar** is the zone bar for page-scoped controls. Every page that needs it renders the same `<div class="toolbar">` shell (see `_shared/_toolbar.html`) whose children all right-align. There are up to two pieces: the filter link `.toolbar-filter-link` (list pages opting into `routes.search`), and the page-action `<menu class="toolbar-right">` (Create, Edit, Delete, Favorite, Export...). The action cluster is a `<menu>` — HTML's native "list of commands" element — so the page's **primary resource actions** are marked up as the toolbar a screen reader / browser already expects. Each action is a `<li>` child of the menu. The filter link reads `Filters` when none are applied and switches to a short summary ("Type: Seeking, Description: needle, +2 more filters" — first two inline, the rest collapsed) when any are; it always opens the dedicated `/<collection>/search` page, where the form's own "Clear" button owns clearing. Detail pages omit the filter link and render only the action menu. Pages without page-scoped controls leave the block empty.

Inline / subresource actions inside the page body (per-row delete buttons on `clinicians/form_edit.html`'s licensure list, inline-add-form submits) are **not** primary resource actions and stay where they are — they act on a single subentity, not on the page's resource.

Edit forms keep a bottom `<a class="secondary outline">Cancel</a>` pointing at the resource's detail page — a deliberate "abandon this edit" affordance. The Cancel link carries a `data-cancel-btn` attribute; the `actions` macro injects a tiny inline script that marks the form dirty on the first `input` event and shows a `confirm("Discard changes?")` dialog on Cancel click when the form is dirty. Untouched forms navigate immediately. The script is only emitted in form layout (`wrapper="form"`) — toolbar Cancel links (detail-page Edit/Delete clusters) are not guarded because they never sit adjacent to an editable form.

## Partial convention

Files prefixed with `_` (e.g. `_breadcrumb.html`, `_toolbar.html`, `_provider_row.html`) are partials, `{% include %}`d from full pages — never rendered directly by routes. A partial documents its required context in a `{# ... #}` comment at the top and guards visibility on a single named flag (`{% if can_edit %}`). The handler computes the flag using [`../authz.py`](../authz.py) predicates; partials never introspect `current_user` to decide visibility. Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

## Shared macros (`_shared/`)

- `form_fields.html` — `text_field`, `textarea_field`, `select_field`, `radio_bool_field`, `multi_select_field`, `time_grid_field`, and the schema-driven `field_for`. `<select>` macros iterate over the controlled-vocabulary tuples from [`../../domain/models/enums.py`](../../domain/models/enums.py) and resolve labels from `*_LABELS` — both registered as Jinja globals in [`../rendering/templating.py`](../rendering/templating.py). Adding a value to a tuple flows automatically to every form using these macros.
- `forms.html` — `inline_add_form(...)`: single-fieldset form skeleton for sub-resource add forms.
- `sections.html` — `list_or_empty(...)`: `<ul>` or empty-state. Caller passes the `<li>` body via `{% call(item) %}...{% endcall %}`.
- `actions.html` — `actions(submit_label=None, cancel_url=None, edit_url=None, edit_label="Edit", delete_url=None, delete_confirm=None, delete_label="Delete", wrapper="form")`: the unified action cluster. `wrapper="form"` (default) emits a `<div class="form-actions">` Save / Cancel / Delete row for entity create/edit forms; `wrapper="toolbar"` emits raw `<li>` items consumed by the `page_toolbar`'s `<menu class="toolbar-right">` for detail-page Edit / Delete clusters. The vocabulary table at the top of the file documents which Pico classes each axis (primary / secondary / neutral / destructive) uses. Also exports `confirm_delete_button(...)`: a bare HTMX `hx-delete` button with confirm dialog, for inline sub-resource row deletes that sit outside any action cluster.
- `_card.html` — `card(id, headline_url, headline, subtitle=None, data_kind=None)`: the universal list-item card. Every `/<collection>` list page wraps its items in this macro and provides the per-resource body (and optional `<footer>`) via `{% call %}`. The card emits an `<article class="entity-card" data-row-id="…">` with a header band carrying the headline link and an optional `<small class="meta">` subtitle. Tests select rows by `article[data-row-id="…"]`. Fact-row bodies use a `<section class="entity-facts">` containing a `<dl>` of `<div data-fact="key">` rows so tests resolve fact cells via `div[data-fact="…"] dd` rather than the display-string `<dt>` text. The post family's `posts/_shared/_item.html` composes `card` + `_facts_block` for its kind-specific body; non-post lists call `card` directly with an inline `<section class="entity-facts">`.
- `_clinician_card.html` — `clinician_card(clinician)`: the shared clinician directory card, used by `/clinicians`, `/users/me/favorites`, `/users/{id}/clinicians`, and the embedded preview on `/users/{id}`. Headline is `"{first_name} {last_name}"` (falls back to whichever is set, then to the literal `"Unnamed clinician"`), linked to `/clinicians/{id}`. Body emits Practice / Location / Licensed in / Insurance fact rows. Lives at the framework level (not under the clinicians cluster) because four templates across three clusters render it; cross-cluster template imports aren't allowed (see the layering rule).
- `_toolbar.html` — `page_toolbar(active_filters=(), search_url=None)`: the toolbar shell that both `views/list.html` and `views/detail.html` compose. Emits a right-aligned `<div class="toolbar">` strip with up to two pieces — a filter link `<a class="toolbar-filter-link">` (omitted when `search_url` is `None`, as on detail pages) and the action `<menu class="toolbar-right">` (caller body is `<li>` items). The filter link reads ``Filters`` when none are active and collapses to a two-chip-plus-`+N` summary otherwise. There is no in-toolbar Clear-all — the search page's form owns clearing. On list pages the context comes from `handle_list` (`active_filters`, `search_url`); detail pages pass no args.
- `pagination.html` — `pagination(page_meta, paginator_base_query)`: Prev / Page N / Next footer rendered automatically by `views/list.html` after the `{% block content %}`. Reads the `Page` snapshot from [`../dispatch/pagination.py`](../dispatch/pagination.py) (set by `handle_list` and the bespoke list handlers) and emits nothing when the result fits on a single page. `paginator_base_query` is the request's query string with `page=` stripped, so the Prev/Next links round-trip filter state across page navigation.

Every list view uses cards via `_card.html` — no table-based list views exist. Tables for list views were removed in favor of cards because the polymorphic post family (`/openings`, `/referrals`) already needed cards for its description-led rows, and consolidating on one shape avoids the "is this resource a table or a card?" decision for new entities.

The search-page form (`views/search.html`) reads the `Filter` instances declared on the spec; the macro picks the right control by `f.kind`, `f.multi`, and `f.radio` (search input for `TextFilter`; `<select>` with "Any" for single-choice; a Pico toggle radio-button group for `ChoiceFilter(radio=True)`; a `<fieldset class="search-checkbox-fieldset">` of single-click checkboxes for `ChoiceFilter(multi=True)` — long choice sets, `>12` options, also get `.search-checkbox-grid` for a responsive multi-column layout, see #583). Search-page multi-choice and create/edit-form multi-select diverged deliberately: the search page favours single-click discoverability over compactness, while the create/edit forms keep the shared `<select multiple>` widget (`multi_select_field`) because their fields are short-listed (services, in-network carriers). `select_field` (for create/edit) is required by default with an optional disabled placeholder.

## Entity form pages

`views/form_new.html` and `views/form_edit.html` both wrap their `{% block content %}` in `<div class="entity-form-page">`. The wrapper is what makes the form vocabulary consistent across entities:

- **`--form-max-width: 720px`** caps the form on large screens via `.entity-form-page > form { max-width: var(--form-max-width); }`. Mobile is unchanged.
- **Per-field width caps** keep short, bounded inputs from stretching to the full container width inside the cap (#585). The rules live in `base.html` and select by `name` attribute, so per-template wiring isn't required — naming a new field `location_zip` / `npi` / `expiration_date` / etc. picks up the right tier automatically. Three tiers: narrow (~8rem) for ZIP / state-code selects; medium (~12rem) for NPI, ISO dates, license/parent-org IDs, and every `<input type="date">`; wide (~20rem) for City / Cost / treatment-modality. Fields not on the list inherit Pico's default (fills the column).
- **`<div class="grid">`** (Pico's built-in responsive grid utility) is the way to put two or three short fields on one row. Auto-collapses to one column under 768px, so mobile stays single-column. Use it for natural pairs/triples (City/State/ZIP, Start date/End date, In-person/Virtual sessions) — not for long fields.
- **`{{ actions(submit_label, cancel_url=..., delete_url=..., delete_confirm=...) }}`** (from [`_shared/actions.html`](_shared/actions.html)) is the canonical bottom-of-form action cluster. Save lives left; Cancel next to it; Delete is right-aligned via `.form-actions-destructive { margin-left: auto }` so a misfire on the wrong button stays unlikely. On mobile the cluster wraps to full-width column. Every entity create/edit form should end with this macro instead of hand-rolling a `<button>` or `<p><a>Cancel</a></p>`. The same macro with `wrapper="toolbar"` powers detail-page Edit/Delete clusters.
- **Helper text** passes as the `help=` parameter on any input macro. The macro emits a `<small id="<name>-helper">` **inside the wrapping `<label>` after the input** and links the input via `aria-describedby` — Pico's canonical pattern ([docs](https://picocss.com/docs/forms/input)). Writing a bare `<small>` next to a macro call is forbidden — it renders as a sibling of the `<label>`, breaks the aria link, and visually drifts from the field. Pinned by [`_shared/test_form_fields.py::test_no_orphan_small_next_to_macro_call`](_shared/test_form_fields.html); see [`_shared/form_fields.html`](_shared/form_fields.html) docstring for the full vocabulary. Fieldset-scoped helper text (one helper spanning two or three inputs in a `.grid`) renders as a `<small>` child of the `<fieldset>` after the inputs — also Pico-canonical.

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
- Per-entity rendering is exercised indirectly via route tests under [`../../domain/routes/`](../../domain/routes/). Selector conventions for template tests live in [`../../../tests/README.md`](../../../tests/README.md).
