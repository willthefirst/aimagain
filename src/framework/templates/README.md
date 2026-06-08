# Framework templates: chrome + generic view types

The framework's template root holds the domain-agnostic pieces: the site shell, the cross-resource macro library, and the generic view-type templates that domain pages extend. Nothing here knows what a "user" or "clinician" is — it reads context vars and blocks from whichever domain template extends it.

```
src/framework/templates/
├── base.html         ← every page extends this. HTMX setup + the unified page-header band + content/footer slots.
├── _shared/          ← cross-resource macros + partials (form fields, table chrome, breadcrumb/toolbar primitives, the `_page_header.html` band, etc.).
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

A template under `<resource>/` in either root may only `{% extends %}` / `{% include %}` / `{% from %}` / `{% import %}` from: a root-level file (`base.html`), its own directory, `_shared/`, or `views/`. Cross-cluster references (e.g. `posts/...` from `clinicians/...`) mean the partial is *de facto* shared and belongs in `_shared/`. Enforced by [`../../../scripts/dev/template_imports_check.py`](../../../scripts/dev/template_imports_check.py) (runs in `dev lint` and pre-commit).

## Generic view-type templates (`views/`)

Each view-type template fills the same unified page-header band (nav + breadcrumb + toolbar + boundary rule, see "Page chrome contract" below) from `base.html` with the breadcrumb and toolbar shape that matches the verb. A child template extending one of these declares only what's unique: a label, a URL, the body markup, and an optional action cluster.

| View type     | Breadcrumb back target                    | Toolbar                                    | Child must declare                                       |
| ------------- | ----------------------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| `list.html`   | _(auto-injected when `_breadcrumb_items` is in context — see below)_ | optional filter widget + actions cluster   | `resource_label`, `content`. Optional: `actions`, `filters`/`filter_action`/`filter_values` (context). |
| `detail.html` | `← Resource`                              | optional actions cluster                   | `resource_label`, `current_label`, `content`, `resource_url` (context). Optional: `actions`. |
| `form_new.html` | `← Resource`                            | none — form's submit button is the action  | `resource_label`, `content`, `resource_url` (context). H1 = `create_heading`, sourced from `entity_create_label(spec.name, kind=...)` via the form handler — children don't override the H1. |
| `form_edit.html` | `← <current>`                          | none — form's Save/Cancel buttons are the actions | `resource_label`, `current_label`, `content`, `resource_url`, `resource_detail_url` (context). `current_label` is the **specific resource being edited** (e.g. `{{ organization.name }}`, `{{ view.headline }}`) — not a generic kind noun. |
| `search.html` | `← Resource`                              | none — form's submit button is the action  | `resource_label` (context). H1 = `filter_heading`, sourced from `entity_filter_label(spec.name)` via the search handler. |

The breadcrumb is always a single back affordance — a left chevron + the deepest clickable parent's label — at every viewport. The macro picks the back target by walking the chain backward to the last item with a non-`None` href.

**Automatic breadcrumbs on subresource list pages.** `mount_related_list` and `mount_edge_routes` inject `_breadcrumb_items` — a list of `(label, href|None)` tuples — into the template context when the parent entity's spec declares `display_label_fn`. `views/list.html` renders the breadcrumb block automatically when `_breadcrumb_items` is present; top-level list pages have no such injection and render no breadcrumb. Child templates that need a custom chain (labels derived from multiple context variables) still override `{% block breadcrumb %}` directly.

### Create / filter labels — single source of truth

Every "Create X" string in the app (the form-page H1, the toolbar Create button, the chrome nav CTA, the polymorphic kind-picker options) and every "Filter X" string (the toolbar Filter link, the dedicated search-page H1) funnels through the helpers in [`../rendering/labels.py`](../rendering/labels.py). Templates call the Jinja-global form (`{{ entity_create_label('opening') }}`, `{{ entity_filter_label('clinician') }}`); the framework's `handle_get_new_form` / `mount_search` / `handle_list` handlers call the spec-direct form (`create_label_for(spec, kind=...)`, `filter_label_for(spec)`) to populate `create_heading` / `filter_heading` in template context. Because both surfaces go through the same function, the button that opens a form and the H1 the user lands on cannot drift — pinned by `framework/rendering/test_labels.py`.

The "Create X" noun resolves to: per-kind `list_label` from the discriminator registry when a polymorphic spec is in play (`Create clinician opening`, `Create program intake`, `Create client referral`), otherwise the spec's `singular_label` (which defaults to `name` — `Create organization`, `Create clinician`, `Create program`). The "Filter X" plural is always the spec's `url_collection` (`Filter clinicians`, `Filter openings`).

### Why view-type templates

Before this layer existed, every domain template manually rewired `{% block breadcrumb %}` and `{% block toolbar %}` from `_shared/` macros (`breadcrumb`, `page_toolbar`). That worked but offered no vocabulary — a reader had to scan 15 lines of imports and block overrides to confirm "this is the list view of clinicians." `views/list.html` puts that statement in line 1: `{% extends "views/list.html" %}`. The chrome wiring is a property of the view type, not a repeated incantation.

The macros under `_shared/` are still the primitives — `views/*` compose them. A page that needs a chrome shape the view templates don't express (the `/auth/*` flow's centered single-card layout, the post feed's `<ul>` body) extends `base.html` directly or composes the macros by hand.

## Page chrome contract

Every page extending `base.html` lands the same unified page-header **band** — a single `<header class="page-header">` ([`_shared/_page_header.html`](_shared/_page_header.html)) that stacks the chrome rows and closes with **one** horizontal rule. The rule is the page's only divider and sits at the **same Y on every app page at a given screen size**. Two rows are reserved to make that true, both intrinsically (no pinned size units, so the boundary still changes across screen sizes):

- **Breadcrumb row** — pages with no real breadcrumb (list pages) get an invisible back-affordance placeholder (`.page-header-crumb-placeholder`, `visibility: hidden`), so a list page's rule lines up with a detail page's.
- **Toolbar action row** — a button is taller than the bare `<h1>`, so a hidden non-interactive reserve `<button class="toolbar-reserve">` shares the H1's grid cell on every toolbar; the row is always one real-button tall whether or not the page has actions. The actions cell still auto-flows (to col 2 on desktop, to row 2 in the ≤640px stack — where actions-below-heading is the intended layout).

From top to bottom:

```
┌───────────────────────────────────────────────────────────┐
│ <header class="page-header">                              │  ← `_shared/_page_header.html`
│   primary nav        brand + auth-aware links             │
│   breadcrumb row     ← Resource   (hidden placeholder if none) │  ← captured `{% block breadcrumb %}`
│   toolbar row        <h1> title              [actions ▶]  │  ← captured `{% block toolbar %}`
│   ─────────────────────────────────────────────────────  │  ← single `<hr>`
├───────────────────────────────────────────────────────────┤
│ (onboarding banner removed)                               │
│ subtitle (optional)  NPI · Verified                       │  ← `{% block subtitle %}` (rendered below the rule, top of `<main>`)
│ page content                                              │  ← `{% block content %}`
├───────────────────────────────────────────────────────────┤
│ <footer> site chrome           &copy; … · support@ …      │  ← `{% block footer %}` (default body in `base.html`)
└───────────────────────────────────────────────────────────┘
```

`{% include %}` can't see the including template's blocks, so `base.html` captures the `breadcrumb` / `toolbar` / `subtitle` block output into context vars and hands the pre-rendered HTML to the band partial. Children still just override `{% block breadcrumb %}` / `{% block toolbar %}` / `{% block subtitle %}` — the capture indirection is transparent. The band's lower rows + rule render only when there's app chrome to show (any breadcrumb/toolbar content, or an authenticated viewer), so anonymous public pages (landing, the `/auth/*` flow) keep their bare brand nav with no rule.

**Body layout.** `<header>`, `<main>`, and `<footer>` are direct siblings of `<body>`, and `<body>` is a three-row CSS grid (`grid-template-rows: auto 1fr auto`) sized to `min-height: 100dvh`. Short pages pin the footer to the viewport bottom instead of leaving it floating; tall pages flow normally and push the footer below. The landing page reuses this scaffold to vertically center its hero inside the `<main>` row (see [`../../domain/templates/landing.html`](../../domain/templates/landing.html)).

**Site footer** (`{% block footer %}`) renders on every page from the default body in `base.html` — a centered `<small>` with the copyright line and a `mailto:` to support. Pages can override the block to swap or extend the line; today none do.

**Primary nav** lives in `base.html` and renders on every screen (authed *and* anonymous) as a single `<ul id="primary-nav">`. The brand sits on the left; when authed, inline links push to the right via `margin-left: auto` on the first link: Posts (`/posts`), Profile (`/users/me`), and Sign out (an `<a hx-post="/auth/sign-out">` — the route returns `HX-Redirect`). Anonymous visitors see only the brand; the chrome carries no Login shortcut (visitors enter the auth flow from the landing page CTA). Active state is matched against `request.url.path`. Pages don't extend it.

The active tab carries `aria-current="page"` plus `class="contrast"`, and `base.html` styles `nav[aria-label="Primary"] a[aria-current="page"]` with a bottom underline + font-weight bump so the section reads at a glance — Pico's default `aria-current` tint alone was too subtle (#589). The rule scopes to the primary nav so breadcrumb / pagination links that also set `aria-current` keep their lighter treatment. Subpaths under each URL family (e.g. `/posts/{id}`, `/posts/form?kind=clinician_opening`) light the parent section tab. `test_views.py` pins the URL → active-tab mapping, and `test_primary_nav_omits_login_link_for_anonymous_visitors` pins the no-Login contract across every anonymous-accessible URL family.

**Breadcrumb zone bar** (`{% block breadcrumb %}`, macro in `_shared/_breadcrumb.html`) renders Pico's native breadcrumb above the toolbar. Every authenticated page extends the block — chrome consistency is the goal. The shape follows the resource hierarchy `list > detail > edit/new`, each level appending one segment:

| Page type        | URL example                    | Breadcrumb                            |
| ---------------- | ------------------------------ | ------------------------------------- |
| Resource list    | `/posts`                       | `Posts`                               |
| Resource detail  | `/posts/{id}`                  | `Posts › Post`                        |
| Resource new     | `/posts/form`                  | `Posts › New`                         |
| Resource edit    | `/posts/{id}/form`             | `Posts › Post › Edit`                 |
| Subresource list | `/users/{id}/clinicians`        | `Users › <username> › Clinicians`      |

Every prior segment is a link (`<a href="…">`); the trailing segment is the current page (no `href`, gets `aria-current="page"`). List pages render no breadcrumb at all; the band reserves the breadcrumb row with a hidden placeholder (`.page-header-crumb-placeholder`) so the boundary rule still lines up with detail/form pages — the strip height stays consistent across pages without a stray single-segment trail.

Public auth-flow pages (`/auth/login`, `/auth/register`, …) opt out — they aren't in the resource hierarchy.

**Toolbar / action bar** is the zone bar for page-scoped controls. Every page that needs it renders the same `<div class="toolbar">` shell (see `_shared/_toolbar.html`) whose children all right-align. The toolbar carries the page `<h1>` and an optional page-action `<menu class="toolbar-right">` (Create, Edit, Delete, Favorite, Export...). The action cluster is a `<menu>` — HTML's native "list of commands" element — so the page's **primary resource actions** are marked up as the toolbar a screen reader / browser already expects. Each action is a `<li>` child of the menu. **Filters never live in the toolbar.** When an entity spec declares `filters=(…)`, the list view renders a sidebar (see the browse-layout note below) whose header links to the dedicated `/<collection>/search` page; entities with no declared filters have no filter UI at all. Pages without page-scoped controls leave the block empty.

Inline / subresource actions inside the page body (per-row delete buttons on `clinicians/form_edit.html`'s licensure list, inline-add-form submits) are **not** primary resource actions and stay where they are — they act on a single subentity, not on the page's resource.

Edit forms keep a bottom `<a class="secondary outline">Cancel</a>` pointing at the resource's detail page — a deliberate "abandon this edit" affordance. The Cancel link carries a `data-cancel-btn` attribute; the `actions` macro injects a tiny inline script that marks the form dirty on the first `input` event and shows a `confirm("Discard changes?")` dialog on Cancel click when the form is dirty. Untouched forms navigate immediately. The script is only emitted in form layout (`wrapper="form"`) — toolbar Cancel links (detail-page Edit/Delete clusters) are not guarded because they never sit adjacent to an editable form.

## Partial convention

Files prefixed with `_` (e.g. `_breadcrumb.html`, `_toolbar.html`, `_credential_row.html`) are partials, `{% include %}`d from full pages — never rendered directly by routes. A partial documents its required context in a `{# ... #}` comment at the top and guards visibility on a single named flag (`{% if can_edit %}`). The handler computes the flag using [`../authz.py`](../authz.py) predicates; partials never introspect `current_user` to decide visibility. Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

## Shared macros (`_shared/`)

- `form_fields.html` — `text_field`, `textarea_field`, `select_field`, `checkbox_field`, `multi_select_field`, `entity_select_field`, `composite_select_field`, and the schema-driven `field_for`. `<select>` macros iterate over the controlled-vocabulary tuples from [`../../domain/models/enums.py`](../../domain/models/enums.py) and resolve labels from `*_LABELS` — both registered as Jinja globals in [`../rendering/templating.py`](../rendering/templating.py). Adding a value to a tuple flows automatically to every form using these macros.
- `forms.html` — `inline_add_form(...)`: single-fieldset form skeleton for sub-resource add forms.
- `sections.html` — `list_or_empty(...)`: `<ul>` or empty-state. Caller passes the `<li>` body via `{% call(item) %}...{% endcall %}`.
- `actions.html` — `actions(submit_label=None, cancel_url=None, edit_url=None, edit_label="Edit", delete_url=None, delete_confirm=None, delete_label="Delete", wrapper="form")`: the unified action cluster. `wrapper="form"` (default) emits a `<div class="form-actions">` Save / Cancel / Delete row for entity create/edit forms; `wrapper="toolbar"` emits raw `<li>` items consumed by the `page_toolbar`'s `<menu class="toolbar-right">` for detail-page Edit / Delete clusters. The vocabulary table at the top of the file documents which Pico classes each axis (primary / secondary / neutral / destructive) uses. Also exports `confirm_delete_button(...)`: a bare HTMX `hx-delete` button with confirm dialog, for inline sub-resource row deletes that sit outside any action cluster.
- `_card.html` — `card(id, headline_url, headline, subtitle=None, data_kind=None)`: the universal list-item card. Every `/<collection>` list page wraps its items in this macro and provides the per-resource body (and optional `<footer>`) via `{% call %}`. The card emits an `<article class="entity-card" data-row-id="…">` with a header band carrying the headline link and an optional `<small class="meta">` subtitle. Tests select rows by `article[data-row-id="…"]`. Fact-row bodies use a `<section class="entity-facts">` containing a `<dl>` of `<div data-fact="key">` rows so tests resolve fact cells via `div[data-fact="…"] dd` rather than the display-string `<dt>` text. The post family's `posts/_shared/_item.html` composes `card` + `_facts_block` for its kind-specific body; non-post lists call `card` directly with an inline `<section class="entity-facts">`.
- `_clinician_card.html` — `clinician_card(clinician)`: the shared clinician directory card, used by `/clinicians`, `/users/me/favorites`, `/users/{id}/clinicians`, and the embedded preview on `/users/{id}`. Headline is `"{first_name} {last_name}"` (falls back to whichever is set, then to the literal `"Unnamed clinician"`), linked to `/clinicians/{id}`. Body emits Practice / Location / Licensed in / Insurance fact rows. Lives at the framework level (not under the clinicians cluster) because four templates across three clusters render it; cross-cluster template imports aren't allowed (see the layering rule).
- `_feed_row.html` — `post_feed_row(post, show_poster=True)` and `post_feed_empty(message, link_href=None, link_label=…)`: the description-led feed row + empty state for `Post` lists. Emits `<article class="post-feed-row" data-kind="…">` (type-tag pill · poster · timestamp, full-width headline link, muted meta strip); `post_feed_empty` emits `<article class="post-feed-empty">`. Reads the `post_card_view` / `post_feed_headline` template globals and the `can_read_full_feed` context flag. Rendered by the home feed (`home.html`), `/posts` (`posts/list.html`), and the per-owner projections (`/clinicians/{id}/openings`, `/clinicians/{id}/referrals`, `/organizations/{id}/intakes`). Lives at the framework level — same rationale as `_clinician_card.html`: it's rendered across the posts, home, clinicians, and organizations clusters, and cross-cluster template imports aren't allowed.
- `_filter_field.html` — `filter_field(f, value)`: renders one `Filter` spec object as an inline form control. Shared by `views/list.html` (browse-layout sidebar) and `views/search.html` (full-page search) so both surfaces stay in sync as filter declarations change. Control selection: `TextFilter` → `<input type="search">`; `ChoiceFilter` single → `<select>`; `ChoiceFilter(radio=True)` → toggle radio group; `ChoiceFilter(multi=True)` → `<fieldset class="search-checkbox-fieldset">` of single-click checkboxes (long sets `>12` options also get `.search-checkbox-grid`); `FlagFilter` → single labeled checkbox.
- `_toolbar.html` — `page_toolbar(heading)`: the toolbar shell that every page-scoped view composes (`views/list.html`, `views/detail.html`, `views/form_new.html`, `views/form_edit.html`, `views/search.html`, plus the bespoke `home.html` and access pages). Emits a `<div class="toolbar">` strip carrying the page `<h1>` on the left and an optional action `<menu class="toolbar-right">` on the right (caller body is `<li>` items). No filter link, no search affordance, no other zones — filters live in the list view's sidebar (see browse-layout below). The macro emits **no** separator — the single boundary rule below the toolbar is owned by the page-header band (`_page_header.html`).
- `_picker.html` — `picker(options)`: the "choose your path" card grid. Each option is a dict of `href` / `heading` / `description`; the macro emits a `<div class="picker">` grid wrapping one `<a class="picker-option"><hgroup><h2>…</h2><p>…</p></hgroup></a>` card per option. The `.picker` / `.picker-option` styling lives in `framework.css` — bordered cards with a link-coloured heading and muted (non-underlined) description, so the chooser reads as the page's primary action rather than a stack of underlined links. Two usages, one component: a *discriminator/type picker* funnels to a kind-/type-specific sub-form of the **same** resource via a selecting query param (`/posts/form` `?kind=`, `/organizations/form` `?type=`); a *dispatching picker* points its cards at **other** resources' create forms (e.g. an identity picker → `/clinicians/form` and `/organizations/form`). The macro only takes `{href, heading, description}` (plus an optional `selected` flag that renders the current path as a non-clickable marked card) — self- vs cross-resource hrefs are the caller's business. Extracted from the posts pattern (#704); pinned by [`_shared/test_picker.py`](_shared/test_picker.py).
- `pagination.html` — `pagination(page_meta, paginator_base_query)`: Prev / Page N / Next footer rendered automatically by `item_list` inside `{% block list_body %}`. Reads the `Page` snapshot from [`../dispatch/pagination.py`](../dispatch/pagination.py) (set by `handle_list` and the bespoke list handlers) and emits nothing when the result fits on a single page. `paginator_base_query` is the request's query string with `page=` stripped, so the Prev/Next links round-trip filter state across page navigation.

Every list view uses cards via `_card.html` — no table-based list views exist. Tables for list views were removed in favor of cards because the polymorphic post family (`/posts`, narrowed via `?kind=`) already needed cards for its description-led rows, and consolidating on one shape avoids the "is this resource a table or a card?" decision for new entities.

The browse-layout sidebar and the full-page search form both use `filter_field` from `_shared/_filter_field.html`. When a spec declares `filters=(…)`, `views/list.html`'s `{% block content %}` automatically wraps `{% block list_body %}` in a `.browse-layout` two-column layout (220px sidebar + flexible results), and the framework auto-mounts the dedicated `/<collection>/search` page (no separate `routes.search` flag — declaring filters implies the search route). The sidebar embeds the filter form inline so viewers never navigate away to filter; on narrow viewports the sidebar stacks above results and the inline form is hidden, but the sidebar's header link to `/<collection>/search` remains tappable. Entities with no declared filters render `list_body` full-width without a sidebar and have no filter UI at all. Entity list templates fill `{% block list_body %}` (not `{% block content %}`); `{% block content %}` owns the browse-layout wrapper and is rarely overridden directly.

## Entity form pages

`views/form_new.html` and `views/form_edit.html` wrap `<div class="entity-form-page">` inside `{% block content %}`, then expose `{% block form_content %}` for child templates to fill. Child templates therefore override `form_content` (not `content`) to get the wrapper automatically. The wrapper is what makes the form vocabulary consistent across entities:

- **`--form-max-width: 720px`** caps the form on large screens via `.entity-form-page > form { max-width: var(--form-max-width); }`. Mobile is unchanged.
- **Per-field width caps** keep short, bounded inputs from stretching to the full container width inside the cap (#585). The rules live in [`src/domain/static/css/domain.css`](../../../src/domain/static/css/domain.css) and select by `name` attribute, so per-template wiring isn't required — naming a new field `location_zip` / `npi` / `expiration_date` / etc. picks up the right tier automatically. Three tiers: narrow (~8rem) for ZIP / state-code selects; medium (~12rem) for NPI, ISO dates, license/parent-org IDs, and every `<input type="date">`; wide (~20rem) for City / Cost / treatment-modality. Fields not on the list inherit Pico's default (fills the column).
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
- `test_page_header.py` (colocated): pins the unified band — the toolbar `<h1>` and breadcrumb render *inside* `header.page-header`, list pages reserve the breadcrumb row with a hidden placeholder, exactly one `<hr>` lives in the band (none in `<main>`), plus CSS-regex pins for the no-wrap / truncation / reserved-placeholder rules.
- Per-entity rendering is exercised indirectly via route tests under [`../../domain/routes/`](../../domain/routes/). Selector conventions for template tests live in [`../../../tests/README.md`](../../../tests/README.md).
