from datetime import date, datetime
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.framework.config import settings
from src.framework.rendering.form_fields import field_spec
from src.framework.rendering.route_urls import entity_form_url, entity_url

auto_reload = settings.ENVIRONMENT == "development"


def format_post_date(value: datetime | date | None) -> str:
    """Craigslist-style short date — `May 15` for current-year posts,
    `May 15, 2025` for older. Used by the posts list/detail templates so
    the same timestamp reads the same way in both places.

    `%-d` strips a leading zero from the day (`May 5`, not `May 05`).
    Linux/macOS only; this app runs on neither Windows nor any platform
    that needs `%#d`. If that changes, swap to `strftime('%b %d').lstrip('0')`.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        return ""
    today = date.today()
    if d.year == today.year:
        return d.strftime("%b %-d")
    return d.strftime("%b %-d, %Y")


_env = Environment(
    # Two search roots: framework owns `base.html`, `_shared/` macros, and
    # the generic `views/` chrome; domain owns per-entity templates. The
    # FileSystemLoader resolves names by walking the list, so domain
    # templates can `{% extends "views/list.html" %}` (resolved from
    # framework) and reference `{% from "_shared/..." %}` the same way.
    loader=FileSystemLoader(["src/framework/templates", "src/domain/templates"]),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

# Framework-owned globals: schema-driven form-field helper plus the
# canonical entity URL helpers (`entity_url` / `entity_form_url` — see
# `route_urls.py` and the `template_route_check.py` lint). Everything
# entity-specific — enums, per-kind create schemas, view helpers — is
# registered from `src/domain/template_globals.py`.
_env.globals["field_spec"] = field_spec
_env.globals["entity_url"] = entity_url
_env.globals["entity_form_url"] = entity_form_url
_env.filters["format_post_date"] = format_post_date


def register_template_globals(**kwargs: Any) -> None:
    """Add Jinja globals to the framework's environment.

    Called from `src/domain/template_globals.py` at app load to expose
    domain enums, per-kind create schemas, and view helpers to templates.
    The framework deliberately knows nothing about what gets registered;
    the call site is the domain.
    """
    _env.globals.update(kwargs)


templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": "35729",
    }
