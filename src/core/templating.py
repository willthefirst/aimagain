import os

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

auto_reload = os.getenv("ENVIRONMENT", "development") == "development"

_env = Environment(
    loader=FileSystemLoader("src/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": os.getenv("ENVIRONMENT", "development") == "development",
        "livereload_port": os.getenv("LIVERELOAD_PORT", "35729"),
    }
