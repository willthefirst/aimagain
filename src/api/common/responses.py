from typing import Any

from fastapi import Response, status
from fastapi.responses import JSONResponse

from src.logic._authz import is_admin
from src.models import User


def base_context(user: User | None) -> dict:
    """Flat scalars the chrome layer (`base.html` + identity widgets) reads
    on every render.

    Returning primitives instead of the `User` object means templates
    cannot accidentally introspect identity fields (`{{ user.email }}`)
    and tests can render the chrome with literals rather than
    constructing a User.

    `is_admin` is computed via `src.logic._authz.is_admin` so the rule
    has a single home; templates never re-derive it.
    """
    return {
        "is_authenticated": user is not None,
        "is_admin": is_admin(user),
        "current_username": user.username if user is not None else None,
        "current_user_id": user.id if user is not None else None,
    }


class APIResponse:
    @staticmethod
    def html_response(
        template_name: str,
        context: dict,
        request: Any,
        *,
        current_user: User | None = None,
    ) -> Any:
        """
        Helper for HTML responses using templates.

        Merges three context tiers (later tiers overwrite earlier ones):
          1. caller-provided `context`
          2. dev/global context (`is_development`, livereload port)
          3. chrome scalars from `base_context(current_user)`

        Chrome scalars overwrite the caller — they're computed from the
        authenticated `current_user` and are not callable-overridable, so
        a handler can't accidentally pass `is_admin=True` for a non-admin
        viewer.
        """
        from src.core.templating import get_template_context, templates

        merged_context = {
            **context,
            **get_template_context(),
            **base_context(current_user),
        }

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
