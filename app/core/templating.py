from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.config import settings

templates = Jinja2Templates(directory="templates")


def get_secure_url_for(request: Request, name: str, **path_params) -> str:
    """
    Generate URLs that respect HTTPS in production environments.

    This function ensures that form actions and links use HTTPS when:
    1. FORCE_HTTPS setting is enabled, OR
    2. The request came through a reverse proxy with HTTPS (X-Forwarded-Proto header)
    """
    # Generate the base URL using FastAPI's url_for
    url = request.url_for(name, **path_params)

    # Check if we should force HTTPS
    should_use_https = (
        settings.FORCE_HTTPS or request.headers.get("x-forwarded-proto") == "https"
    )

    if should_use_https and url.scheme == "http":
        # Replace HTTP with HTTPS
        url = url.replace(scheme="https")

    return str(url)


# Add the helper function to Jinja2 global context
templates.env.globals["secure_url_for"] = get_secure_url_for
