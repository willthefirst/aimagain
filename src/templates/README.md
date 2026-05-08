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

## Template organization matrix

| Directory  | Purpose                | Templates                                                              |
| ---------- | ---------------------- | ---------------------------------------------------------------------- |
| **/**      | Base layout            | `base.html` - Foundation template (includes site-wide `<nav>` linking to `/posts`, `/users`, `/providers`) |
| **_shared/** | Cross-resource macros | `form_fields.html` (label+control field-render macros), `forms.html` (`inline_add_form` skeleton macro), `sections.html` (`list_or_empty` collection-or-empty-state macro), `actions.html` (`confirm_delete_button` macro). Imported by every resource directory. |
| **auth/**  | Authentication pages   | login, register, forgot/reset password                                 |
| **users/** | User management        | list, detail (also embeds an inline list of providers owned by the user, with empty-state when the user has none), `providers_list.html` (rendered by `GET /users/{id}/providers` and the `GET /users/me/providers` alias; pluralized list with self vs. viewing-other empty-state copy), `_admin_actions.html` partial (shared by list & detail) |
| **posts/** | Posts                  | list, detail, per-kind `new_<kind>.html` + `edit_<kind>.html` thin wrappers around `_<kind>_form.html` partials, `_owner_actions.html` partial (shared by detail) |
| **providers/** | Providers | `list.html` (public HTML directory rendered by `GET /providers`; includes a `license_type` / `issuing_state` filter form whose `selected_*` context values preselect the active filter), `detail.html` (read-only HTML detail rendered by `GET /{id}`; shows practice fields, licensures, educations, certifications; an Edit link is rendered for the owner or an admin only), `new.html` (create form), `edit.html` (edit form with practice-fields PATCH plus three sub-resource sections — licensures, educations, certifications — each with inline add form + per-row delete; uses `list_or_empty`, `inline_add_form`, and `confirm_delete_button` from `_shared/`). The "list providers owned by user X" view lives in `users/providers_list.html`, not here. |
| **me/**    | Personal/profile pages | user profile                                                           |

### Reusable partial convention

Files prefixed with `_` (e.g. `_admin_actions.html`) are **shared partials** intended to be `{% include %}`d from multiple full pages. They are not rendered directly by routes. The convention exists so that, e.g., adding a new admin button to `users/_admin_actions.html` automatically appears on both the user list and the user detail page without per-page edits.

A partial documents its required context at the top in a `{# ... #}` comment, and is responsible for its own access guards (`{% if current_user.is_superuser %}` etc). Backend authorization is enforced separately in the logic layer — the template guard is presentation only.

### Shared CRUD macros (`_shared/`)

CRUD templates pull from a single `_shared/` directory rather than duplicating the same patterns per resource. Four files, each with a narrow purpose:

1. **`_shared/form_fields.html`** — field-render macros: `text_field`, `textarea_field`, `select_field`, `filter_select_field`, `radio_bool_field`, `multi_select_field`, `time_grid_field`. Each emits a label + control + line-breaks. The `<select>` and checkbox macros iterate over a controlled-vocabulary tuple from [`src/models/enums.py`](../models/enums.py) and look display labels up in the matching `*_LABELS` dict — both registered as Jinja globals in [`src/core/templating.py`](../core/templating.py). Adding a value to a tuple flows automatically to every form using these macros. `select_field` is for create/edit forms (required by default; optional disabled-placeholder); `filter_select_field` is for filter forms on list pages (never required; leading "Any" option is selectable so users can clear filters).
2. **`_shared/forms.html`** — `inline_add_form(action, legend, submit_label, method="post")`: single-fieldset form skeleton used by sub-resource sections (e.g. licensure / education / certification add forms in `providers/edit.html`). Forms with multiple fieldsets stay hand-rolled.
3. **`_shared/sections.html`** — `list_or_empty(items, list_class, empty_message)`: `<ul>`-of-items or empty-state `<p>`. Caller passes the per-row `<li>` body via `{% call(item) %}…{% endcall %}`. The `<section>`/`<h2>` wrapper is left to the caller (varies too little to be worth abstracting).
4. **`_shared/actions.html`** — `confirm_delete_button(url, confirm_message, label="Delete")`: HTMX `hx-delete` button with confirm dialog. Used by `posts/_owner_actions.html`, `users/_admin_actions.html`, and the per-row deletes in `providers/edit.html`.

The labels-vs-tuple guardrail (`test_labels_cover_their_tuples`) lives in `src/schemas/test_post.py`; if a value lands in a tuple without a matching label, the form's `<select>` would render a `KeyError` at request time, so the test catches it at CI time instead.

### Per-kind form partials (posts/)

The two intake forms (`client_referral`, `provider_availability`) each have a create page and an edit page. Rather than duplicate the field set across the two pages — and across the two kinds — `posts/_<kind>_form.html` (`_client_referral_form.html`, `_provider_availability_form.html`) wraps the `_shared/form_fields.html` macros into one form-body macro per kind, encoding field order, section grouping, labels, and required/optional state. Both `new_<kind>.html` and `edit_<kind>.html` then collapse to ~5 lines that call the form macro with `(hx_method, action, submit_label, post=...)`. The new vs edit difference reduces to URL + submit label + prefilled values.

## Directory structure

```
templates/
├── base.html                    # Foundation template with HTMX setup
├── _shared/                     # Cross-resource macros (imported by every resource dir)
│   ├── form_fields.html         # Field-render macros (text_field, select_field, …)
│   ├── forms.html               # inline_add_form skeleton macro
│   ├── sections.html            # list_or_empty collection-or-empty-state macro
│   └── actions.html             # confirm_delete_button macro
├── auth/                        # Authentication flow templates
│   ├── login.html              # User login form
│   ├── register.html           # User registration form
│   ├── forgot_password.html    # Password reset request
│   └── reset_password.html     # Password reset form
├── users/                      # User management templates
│   ├── list.html               # User directory listing
│   ├── detail.html             # User detail page
│   └── _admin_actions.html     # Reusable admin-actions partial
├── posts/                      # Post templates
│   ├── list.html               # Post listing
│   ├── detail.html             # Post detail (includes _owner_actions.html)
│   ├── new_client_referral.html       # Thin wrapper over _client_referral_form.html
│   ├── edit_client_referral.html      # Thin wrapper over _client_referral_form.html
│   ├── new_provider_availability.html # Thin wrapper over _provider_availability_form.html
│   ├── edit_provider_availability.html
│   ├── _client_referral_form.html      # Per-kind form body (used by new + edit)
│   ├── _provider_availability_form.html
│   └── _owner_actions.html     # Reusable owner-actions partial (Edit/Delete)
├── providers/                  # Provider templates
│   ├── list.html               # Public directory listing with license_type / issuing_state filter
│   ├── detail.html             # Read-only detail page (GET /{id})
│   ├── new.html                # Create form
│   └── edit.html               # Edit form: practice fields PATCH + three sub-resource add/delete sections
└── me/                         # Personal user pages
    └── profile.html            # User's profile page
```

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
