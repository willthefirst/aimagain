# Templates: HTML presentation layer

The `templates/` directory contains **Jinja2 HTML templates** that define the user interface presentation layer for the Aimagain application, providing server-side rendered pages with HTMX integration for dynamic interactions.

## 🎯 Core philosophy: Server-side rendered progressive enhancement

Templates provide **semantic HTML foundation** with progressive enhancement through HTMX, ensuring the application works without JavaScript while providing rich interactive experiences when available.

### What we do ✅

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
    <title>{% block title %}AI again{% endblock %}</title>
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

### What we don't do ❌

- **Business logic**: Templates only handle presentation, logic stays in routes/services
- **Data processing**: Data transformation happens in logic layer before templates
- **Authentication logic**: Auth decisions made before template rendering
- **Client-side application state**: Use HTMX for interactions, not complex state management

**Example**: Don't put business logic in templates:

```html
<!-- ❌ Wrong - business logic in template -->
{% if conversation.participants|length > 2 and user.is_premium %}
<button>Add More Participants</button>
{% endif %}

<!-- ✅ Correct - logic in route/processing layer -->
{% if can_add_participants %}
<button>Add More Participants</button>
{% endif %}
```

## 🏗️ Architecture: Presentation layer with template inheritance

**Base Template → Feature Templates → Specific Pages**

Templates use inheritance for consistent layout and feature-specific customization.

## 📋 Template organization matrix

| Directory          | Purpose                 | Templates                              |
| ------------------ | ----------------------- | -------------------------------------- |
| **/**              | Base layout and shared  | `base.html` - Foundation template      |
| **auth/**          | Authentication pages    | login, register, forgot/reset password |
| **conversations/** | Conversation management | list, detail, new conversation forms   |
| **users/**         | User management         | user listing and profiles              |
| **me/**            | Personal/profile pages  | user's conversations, invitations      |

## 📁 Directory structure

```
templates/
├── base.html                    # Foundation template with HTMX setup
├── auth/                        # Authentication flow templates
│   ├── login.html              # User login form
│   ├── register.html           # User registration form
│   ├── forgot_password.html    # Password reset request
│   └── reset_password.html     # Password reset form
├── conversations/              # Conversation management templates
│   ├── list.html              # Public conversation listing
│   ├── detail.html            # Individual conversation view
│   └── new.html               # New conversation creation form
├── users/                      # User management templates
│   └── list.html              # User directory listing
└── me/                         # Personal user pages
    ├── conversations.html      # User's personal conversations
    └── invitations.html        # User's pending invitations
```

## 🔧 Implementation patterns

### Base template inheritance pattern

All templates extend the base template for consistency:

```html
<!-- base.html - Foundation template -->
<!DOCTYPE html>
<html>
  <head>
    <title>{% block title %}AI again{% endblock %}</title>
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
{% extends "base.html" %} {% block title %}Conversations - AI again{% endblock
%} {% block content %}
<main>
  <h1>Your conversations</h1>
  <!-- Feature-specific content -->
</main>
{% endblock %}
```

### Htmx integration pattern

Use HTMX for progressive enhancement of forms and interactions:

```html
<!-- Form with HTMX submission -->
<form
  hx-post="/api/conversations"
  hx-target="#conversation-list"
  hx-swap="afterbegin"
  hx-ext="json-enc">
  <label for="invitee_username">Invite User:</label>
  <input type="text" name="invitee_username" id="invitee_username" required />

  <label for="initial_message">Initial Message:</label>
  <textarea name="initial_message" id="initial_message" required></textarea>

  <button type="submit">Start Conversation</button>
</form>

<!-- Target container for HTMX updates -->
<div id="conversation-list">
  {% for conversation in conversations %}
  <!-- Existing conversations -->
  {% endfor %}
</div>
```

### Form template pattern

Consistent form structure across the application:

```html
{% extends "base.html" %} {% block title %}{{ form_title }} - AI again{%
endblock %} {% block content %}
<main>
  <h1>{{ form_title }}</h1>

  {% if error_message %}
  <div class="error-message" role="alert">{{ error_message }}</div>
  {% endif %}

  <form method="post" action="{{ form_action }}">
    {% for field in form_fields %}
    <div class="form-field">
      <label for="{{ field.name }}">{{ field.label }}</label>

      {% if field.type == "textarea" %}
      <textarea
        name="{{ field.name }}"
        id="{{ field.name }}"
        {%
        if
        field.required
        %}required{%
        endif
        %}>
{{ field.value or '' }}</textarea
      >
      {% else %}
      <input
        type="{{ field.type or 'text' }}"
        name="{{ field.name }}"
        id="{{ field.name }}"
        value="{{ field.value or '' }}"
        {%
        if
        field.required
        %}required{%
        endif
        %} />
      {% endif %} {% if field.help_text %}
      <small class="help-text">{{ field.help_text }}</small>
      {% endif %}
    </div>
    {% endfor %}

    <button type="submit">{{ submit_text }}</button>
  </form>
</main>
{% endblock %}
```

### List/detail template pattern

Consistent approach for listing and detailed views:

```html
<!-- List template pattern -->
{% extends "base.html" %} {% block content %}
<main>
  <div class="list-header">
    <h1>{{ list_title }}</h1>
    {% if can_create %}
    <a href="{{ create_url }}" class="create-button">{{ create_text }}</a>
    {% endif %}
  </div>

  {% if items %}
  <ul class="item-list">
    {% for item in items %}
    <li class="item-card">
      <h3><a href="{{ item.detail_url }}">{{ item.title }}</a></h3>
      <p class="item-meta">{{ item.meta_info }}</p>
      {% if item.description %}
      <p class="item-description">{{ item.description }}</p>
      {% endif %}
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="empty-state">{{ empty_message }}</p>
  {% endif %}
</main>
{% endblock %}

<!-- Detail template pattern -->
{% extends "base.html" %} {% block content %}
<main>
  <header class="detail-header">
    <h1>{{ item.title }}</h1>
    <div class="detail-meta">{{ item.meta_info }}</div>
  </header>

  <div class="detail-content">{{ item.content | safe }}</div>

  {% if actions %}
  <div class="detail-actions">
    {% for action in actions %}
    <a href="{{ action.url }}" class="action-button {{ action.style }}"
      >{{ action.text }}</a
    >
    {% endfor %}
  </div>
  {% endif %}
</main>
{% endblock %}
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
        "page_description": "Page description for meta tags",
        "canonical_url": str(request.url),

        # Feature data
        "main_data": data,           # Primary page data
        "metadata": {                # Additional context
            "active_section": "section_name",
            "breadcrumbs": [...],
        }
    }
```

## 🚨 Common template issues and solutions

### Issue: Logic creeping into templates

**Problem**: Complex conditionals and data processing in templates
**Solution**: Move logic to processing layer, pass simple flags to templates

```html
<!-- ❌ Wrong - complex logic in template -->
{% if conversation.participants|selectattr("user_id", "equalto",
current_user.id)|list and conversation.created_at > now() - timedelta(days=7)
and conversation.message_count < 50 %}
<button>Add Participant</button>
{% endif %}

<!-- ✅ Correct - simple flag from processing layer -->
{% if can_add_participant %}
<button>Add Participant</button>
{% endif %}
```

### Issue: Inconsistent form handling

**Problem**: Different forms use different patterns
**Solution**: Use consistent form template patterns

```html
<!-- ✅ Consistent form pattern -->
<form
  method="post"
  action="{{ form_action }}"
  {%
  if
  use_htmx
  %}
  hx-post="{{ form_action }}"
  hx-target="{{ htmx_target }}"
  hx-ext="json-enc"
  {%
  endif
  %}>
  {% for field in form_fields %} {% include "partials/form_field.html" %} {%
  endfor %}

  <button type="submit">{{ submit_text }}</button>
</form>
```

### Issue: Missing accessibility features

**Problem**: Templates don't include proper ARIA labels and semantic HTML
**Solution**: Use semantic HTML and proper accessibility attributes

```html
<!-- ✅ Accessible template structure -->
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

## 🔧 Development workflow

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
async def test_conversation_list_template(client: AsyncClient, authenticated_user):
    response = await client.get("/conversations")

    assert response.status_code == 200
    assert "Your Conversations" in response.text
    assert "Start New Conversation" in response.text
```

## 📚 Related documentation

- [../api/routes/README.md](../api/routes/README.md) - Routes that render these templates
- [../logic/README.md](../logic/README.md) - Processing layer that prepares template context
- [../core/README.md](../core/README.md) - Template configuration and utilities
- [base.html](base.html) - Foundation template for all pages
