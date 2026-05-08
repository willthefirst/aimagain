from typing import Any

from fastapi import Response, status
from fastapi.responses import JSONResponse


class APIResponse:
    @staticmethod
    def html_response(template_name: str, context: dict, request: Any) -> Any:
        """
        Helper for HTML responses using templates.
        Includes global template context for development features.
        """
        from src.core.templating import get_template_context, templates

        # Merge the provided context with global template context
        global_context = get_template_context()
        merged_context = {**global_context, **context}

        return templates.TemplateResponse(request, template_name, merged_context)


def created_response(
    *, id: Any, location: str, hx_redirect: str | None = None
) -> JSONResponse:
    """201 Created with `{"id": str(id)}` body, `Location: <location>`, and
    `HX-Redirect: <hx_redirect or location>`.

    The split lets a route point `Location` at the canonical resource URL
    (per RFC 7231) while sending HTMX clients to a different page (e.g.
    the edit form for the just-created resource).
    """
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(id)},
        headers={"Location": location, "HX-Redirect": hx_redirect or location},
    )


def updated_response(*, body: dict | None = None, hx_redirect: str) -> JSONResponse:
    """200 OK with optional body and `HX-Redirect: <hx_redirect>`."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body or {},
        headers={"HX-Redirect": hx_redirect},
    )


def deleted_response(*, hx_redirect: str) -> Response:
    """204 No Content with `HX-Redirect: <hx_redirect>`. Used when the
    deleted resource's parent or list page is the post-delete landing
    spot."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": hx_redirect},
    )


def refreshed_response() -> JSONResponse:
    """200 OK with empty body and `HX-Refresh: true`. Tells HTMX to reload
    the current page in place (used for actions that affect the current
    view, e.g. user activation flips)."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={},
        headers={"HX-Refresh": "true"},
    )
