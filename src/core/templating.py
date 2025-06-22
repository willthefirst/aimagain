import os

from fastapi.templating import Jinja2Templates

# Enable auto-reload for templates in development mode
auto_reload = os.getenv("ENVIRONMENT", "development") == "development"

templates = Jinja2Templates(directory="src/templates", auto_reload=auto_reload)
