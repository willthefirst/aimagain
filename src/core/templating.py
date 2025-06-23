import os

from fastapi.templating import Jinja2Templates

# Enable auto-reload for templates in development mode
auto_reload = os.getenv("ENVIRONMENT", "development") == "development"

templates = Jinja2Templates(directory="src/templates", auto_reload=auto_reload)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": os.getenv("ENVIRONMENT", "development") == "development",
        "livereload_port": os.getenv("LIVERELOAD_PORT", "35729"),
    }
