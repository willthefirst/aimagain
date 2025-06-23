from fastapi import Request
from fastapi.responses import HTMLResponse

from src.core.templating import get_template_context, templates


def html_response(
    template_name: str, context: dict, request: Request | None = None
) -> HTMLResponse:
    """
    Helper function to render HTML templates.
    Ensures that 'request' is always in the context if not already provided.
    Includes global template context for development features.
    """
    # Get global template context (includes development flags)
    global_context = get_template_context()

    if request and "request" not in context:
        # Ensure request is in context for templates that require it (e.g., for URL generation)
        context["request"] = request
    elif not request and "request" not in context:
        # Raise an error or log if request is critical and missing,
        # or ensure templates handle its absence.
        # For now, we assume templates might not always need it if not passed.
        pass

    # Merge global context with provided context
    merged_context = {**global_context, **context}

    return templates.TemplateResponse(name=template_name, context=merged_context)
