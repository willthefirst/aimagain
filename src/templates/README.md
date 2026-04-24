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

| Directory  | Purpose                | Templates                              |
| ---------- | ---------------------- | -------------------------------------- |
| **/**      | Base layout and shared | `base.html` - Foundation template      |
| **auth/**  | Authentication pages   | login, register, forgot/reset password |
| **users/** | User management        | user listing                           |
| **me/**    | Personal/profile pages | user profile                           |

## Directory structure

```
templates/
├── base.html                    # Foundation template with HTMX setup
├── auth/                        # Authentication flow templates
│   ├── login.html              # User login form
│   ├── register.html           # User registration form
│   ├── forgot_password.html    # Password reset request
│   └── reset_password.html     # Password reset form
├── users/                      # User management templates
│   └── list.html              # User directory listing
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
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": settings.LIVERELOAD_PORT if settings.ENVIRONMENT == "development" else None,

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

## Related documentation

- [API Routes](../api/routes/README.md) - Routes that render these templates
- [Logic Layer](../logic/README.md) - Processing layer that prepares template context
- [Core Layer](../core/README.md) - Template configuration and utilities
