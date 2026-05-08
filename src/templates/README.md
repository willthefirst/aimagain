# Templates: HTML presentation layer

The `templates/` directory contains **Jinja2 HTML templates** that define the user interface presentation layer for the application, providing server-side rendered pages with HTMX integration for dynamic interactions.

## Core philosophy: Server-side rendered progressive enhancement

Templates provide **semantic HTML foundation** with progressive enhancement through HTMX, ensuring the application works without JavaScript while providing rich interactive experiences when available.

### What we do

- **Server-side rendering**: Generate complete HTML pages on the server
- **Progressive enhancement**: Base functionality works without JavaScript, enhanced with HTMX
- **Template inheritance**: Use base templates for consistent layout and structure
- **Component organization**: Organize templates by feature/domain area
- **Semantic HTML**: Use proper HTML semantics for accessibility and SEO

**Example**: Base template with HTMX integration:

```html
<!DOCTYPE html>
<html>
  <head>
    <title>{% block title %}App{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/htmx.org/dist/ext/json-enc.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    {% block head %}{% endblock %}
  </head>
  <body>
    {% block content %}{% endblock %}
  </body>
</html>
```

### What we don't do

- **Business logic**: Templates only handle presentation, logic stays in routes/services
- **Data processing**: Data transformation happens in logic layer before templates
- **Authentication logic**: Auth decisions made before template rendering
- **Client-side application state**: Use HTMX for interactions, not complex state management

**Example**: Don't put business logic in templates:

```html
<!-- Bad - business logic in template -->
{% if items|length > limit and user.is_premium %}
<button>Load More</button>
{% endif %}

<!-- Good - logic in route/processing layer -->
{% if can_load_more %}
<button>Load More</button>
{% endif %}
```

## Architecture: Presentation layer with template inheritance

**Base Template -> Feature Templates -> Specific Pages**

Templates use inheritance for consistent layout and feature-specific customization.

## Layer organization

Templates follow the [cluster pattern](../README.md#domain-entities-and-the-cluster-pattern):

- `base.html` at the parent — foundation template every page extends. Provides the HTMX setup and the site-wide nav.
- `_shared/` at the parent — cross-resource macros importable by every cluster (see [Shared CRUD macros](#shared-crud-macros-_shared) below).
- `<resource>/` — one cluster directory per domain entity. Each holds the templates for that resource's CRUD pages (`list.html`, `detail.html`, optional `new.html`/`edit.html` or per-kind variants) plus any cluster-local partials (filenames prefixed with `_`).

Per-resource specifics — what fields the list shows, which partials a cluster has, route-to-template mapping — live in that resource's [api/routes/](../api/routes/) handler and (when worth writing down) in `<resource>/README.md`. This README documents the rules; the directory listing is the registry of resources.

### Reusable partial convention

Files prefixed with `_` (e.g. `_admin_actions.html`) are **shared partials** intended to be `{% include %}`d from multiple full pages. They are not rendered directly by routes. The convention exists so that, e.g., adding a new admin button to `users/_admin_actions.html` automatically appears on both the user list and the user detail page without per-page edits.

A partial documents its required context at the top in a `{# ... #}` comment, and is responsible for its own access guards (`{% if current_user.is_superuser %}` etc). Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

### Shared CRUD macros (`_shared/`)

CRUD templates pull from a single `_shared/` directory rather than duplicating the same patterns per resource. Four files, each with a narrow purpose:

A template under `<resource>/` may only `{% extends %}` / `{% include %}` / `{% from %}` / `{% import %}` from: the project root (`base.html`), its own directory, or `_shared/`. Anything else is a layering smell — the partial is *de facto* shared and belongs in `_shared/`. The rule is enforced by `scripts/dev/template_imports_check.py`, which runs as part of `dev lint` and as a pre-commit hook.

1. **`_shared/form_fields.html`** — field-render macros: `text_field`, `textarea_field`, `select_field`, `filter_select_field`, `radio_bool_field`, `multi_select_field`, `time_grid_field`. Each emits a label + control + line-breaks. The `<select>` and checkbox macros iterate over a controlled-vocabulary tuple from [`src/models/enums.py`](../models/enums.py) and look display labels up in the matching `*_LABELS` dict — both registered as Jinja globals in [`src/core/templating.py`](../core/templating.py). Adding a value to a tuple flows automatically to every form using these macros. `select_field` is for create/edit forms (required by default; optional disabled-placeholder); `filter_select_field` is for filter forms on list pages (never required; leading "Any" option is selectable so users can clear filters).
2. **`_shared/forms.html`** — `inline_add_form(action, legend, submit_label, method="post")`: single-fieldset form skeleton for sub-resource add forms. Forms with multiple fieldsets stay hand-rolled.
3. **`_shared/sections.html`** — `list_or_empty(items, list_class, empty_message)`: `<ul>`-of-items or empty-state `<p>`. Caller passes the per-row `<li>` body via `{% call(item) %}…{% endcall %}`. The `<section>`/`<h2>` wrapper is left to the caller (varies too little to be worth abstracting).
4. **`_shared/actions.html`** — `confirm_delete_button(url, confirm_message, label="Delete")`: HTMX `hx-delete` button with confirm dialog.

The labels-vs-tuple guardrail (`test_labels_cover_their_tuples`) lives alongside the schema that depends on it; if a value lands in a tuple without a matching label, the form's `<select>` would render a `KeyError` at request time, so the test catches it at CI time instead.

### Per-kind form partials

Resources whose intake forms come in multiple variants (e.g. discriminator-based polymorphic models) follow a two-layer pattern within their cluster: `_<variant>_form.html` defines a per-variant form-body macro that calls the `_shared/form_fields.html` macros; `new_<variant>.html` and `edit_<variant>.html` are ~5-line wrappers that call the form macro with `(hx_method, action, submit_label, prefill=...)`. The new vs edit difference reduces to URL + submit label + prefilled values; the field structure lives in one place per variant.

See the cluster's own README when this pattern is in use.

## Implementation patterns

### Base template inheritance pattern

All templates extend the base template for consistency:

```html
<!-- base.html - Foundation template -->
<!DOCTYPE html>
<html>
  <head>
    <title>{% block title %}App{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    {% block head %}{% endblock %} {% if is_development %}
    <!-- LiveReload for development -->
    <script>
      var script = document.createElement('script')
      script.src =
        'http://localhost:{{ livereload_port }}/livereload.js?snipver=1'
      script.async = true
      document.head.appendChild(script)
    </script>
    {% endif %}
  </head>
  <body>
    {% block content %}{% endblock %}
  </body>
</html>

<!-- Feature template extending base -->
{% extends "base.html" %} {% block title %}Users{% endblock
%} {% block content %}
<main>
  <h1>Users</h1>
  <!-- Feature-specific content -->
</main>
{% endblock %}
```

### Htmx integration pattern

Use HTMX for progressive enhancement of forms and interactions:

```html
<!-- Form with HTMX submission -->
<form
  hx-post="/api/[entities]"
  hx-target="#entity-list"
  hx-swap="afterbegin"
  hx-ext="json-enc">
  <label for="name">Name:</label>
  <input type="text" name="name" id="name" required />

  <button type="submit">Create</button>
</form>

<!-- Target container for HTMX updates -->
<div id="entity-list">
  {% for item in items %}
  <!-- Existing items -->
  {% endfor %}
</div>
```

### Template context pattern

Standard context structure passed from routes:

```python
# In route/processing function
def prepare_template_context(request: Request, user: User, data: Any) -> dict:
    """Standard context preparation for templates."""
    return {
        "request": request,          # Required by FastAPI templates
        "current_user": user,        # Current authenticated user
        "is_authenticated": bool(user), # Authentication status
        **get_template_context(),    # Include environment context (safe development-only features)

        # Page-specific data
        "page_title": "Page Title",
        "main_data": data,           # Primary page data
    }
```

## Common template issues and solutions

### Issue: Logic creeping into templates

**Problem**: Complex conditionals and data processing in templates
**Solution**: Move logic to processing layer, pass simple flags to templates

```html
<!-- Bad - complex logic in template -->
{% if items|selectattr("status", "equalto", "active")|list
and items|length < max_count %}
<button>Add Item</button>
{% endif %}

<!-- Good - simple flag from processing layer -->
{% if can_add_item %}
<button>Add Item</button>
{% endif %}
```

### Issue: Missing accessibility features

**Problem**: Templates don't include proper ARIA labels and semantic HTML
**Solution**: Use semantic HTML and proper accessibility attributes

```html
<!-- Good - accessible template structure -->
<main role="main">
  <h1 id="page-title">{{ page_title }}</h1>

  {% if error_message %}
  <div class="error-message" role="alert" aria-live="polite">
    {{ error_message }}
  </div>
  {% endif %}

  <form aria-labelledby="page-title">
    <label for="username">Username:</label>
    <input
      type="text"
      id="username"
      name="username"
      aria-describedby="username-help"
      required />
    <small id="username-help">Enter your username</small>
  </form>
</main>
```

## Development workflow

### Template development with live reload

During development, templates automatically reload when changed:

```python
# Development server includes live reload
if settings.ENVIRONMENT == "development":
    # LiveReload script automatically injected in base.html
    templates.env.auto_reload = True
```

### Template testing approach

Test templates through route integration tests:

```python
# Test template rendering through routes
async def test_user_list_template(client: AsyncClient, authenticated_user):
    response = await client.get("/users")

    assert response.status_code == 200
    assert "Users" in response.text
```

## Tests

Templates are exercised indirectly by the route tests under [`../api/routes/`](../api/routes/) — they assert on the rendered HTML using `selectolax`. There is no separate test file at this directory level. When adding a new template, extend the relevant route test (or add one) to cover its rendering.

## Related documentation

- [API Routes](../api/routes/README.md) - Routes that render these templates
- [Logic Layer](../logic/README.md) - Processing layer that prepares template context
- [Core Layer](../core/README.md) - Template configuration and utilities
