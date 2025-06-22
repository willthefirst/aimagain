from fastapi import Request
from fastapi.responses import HTMLResponse

from src.core.templating import templates


def html_response(
    template_name: str, context: dict, request: Request | None = None
) -> HTMLResponse:
    """
    Helper function to render HTML templates.
    Ensures that 'request' is always in the context if not already provided.
    """
    if request and "request" not in context:
        # Ensure request is in context for templates that require it (e.g., for URL generation)
        context["request"] = request
    elif not request and "request" not in context:
        # Raise an error or log if request is critical and missing,
        # or ensure templates handle its absence.
        # For now, we assume templates might not always need it if not passed.
        pass

    return templates.TemplateResponse(name=template_name, context=context)
