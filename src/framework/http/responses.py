from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Response, status
from fastapi.responses import JSONResponse

from src.framework.access.authz.authz import is_admin

if TYPE_CHECKING:
    from src.framework.access.actor.actor import Actor


def base_context(user: Actor | None) -> dict:
    """Flat scalars the chrome layer (`base.html` + identity widgets) reads
    on every render.

    Returning primitives instead of the `User` object means templates
    cannot accidentally introspect identity fields (`{{ user.email }}`)
    and tests can render the chrome with literals rather than
    constructing a User.

    `is_admin` is computed via `src.framework.access.authz.authz.is_admin` so the rule
    has a single home; templates never re-derive it.

    `has_clinician_profile` is duck-typed off the user's `clinicians`
    relationship (eagerly loaded on `User` via `lazy="selectin"`, see
    `src/domain/models/users/user.py`). It defaults to `False` when the
    attribute is missing — Actor is a structural Protocol that doesn't
    declare `clinicians`, so test stubs without the attribute read as
    "first-time user" and the chrome shows the profile-setup CTA accordingly.

    `current_user_is_verified` powers the "verify your email" nag
    banner in `base.html`. Anonymous visitors and test stubs without
    the attribute default to `True` so the banner only shows for
    authed users who explicitly have `is_verified=False`. Dev-mode
    users are auto-verified on registration
    (see `src.auth_config.UserManager.on_after_register`) so the
    banner is silent for the seed flow.

    `can_access_network` is the single chrome gate for both feed access
    and the Create Post CTA — any network-verified user (clinician or
    org rep) gets both.
    """
    from src.domain.logic.capabilities import can_access_network

    return {
        "is_authenticated": user is not None,
        "is_admin": is_admin(user),
        "current_username": user.username if user is not None else None,
        "current_user_id": user.id if user is not None else None,
        "has_clinician_profile": bool(getattr(user, "clinicians", None)),
        "current_user_is_verified": (
            True if user is None else bool(getattr(user, "is_verified", True))
        ),
        "can_access_network": can_access_network(user),
    }


class APIResponse:
    @staticmethod
    def html_response(
        template_name: str,
        context: dict,
        request: Any,
        *,
        current_user: Actor | None = None,
        status_code: int = 200,
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

        `status_code` defaults to 200 (the common success path). Form-
        error rerenders pass 4xx (409 duplicate, 401 bad creds, 422
        validation) and the htmx response-targets extension still swaps
        the body in place — see `form_rerender` callers.
        """
        from src.framework.rendering.templating import (
            get_template_context,
            set_viewer,
            templates,
        )

        # Pin the viewer for this render so macros that can't read
        # template context (`entity_link`, `viewer_is_admin`) consult the
        # same identity the route's `current_user_dep` resolved.
        set_viewer(current_user)
        merged_context = {
            **context,
            **get_template_context(),
            **base_context(current_user),
        }

        return templates.TemplateResponse(
            request, template_name, merged_context, status_code=status_code
        )


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


def updated_response(
    *,
    body: dict | None = None,
    hx_redirect: str | None = None,
    hx_refresh: bool = False,
) -> JSONResponse:
    """200 OK with optional body and exactly one of HX-Redirect / HX-Refresh.

    `hx_redirect` sends HTMX to a new URL (PATCH on a parent resource —
    edit succeeded, here's where to go). `hx_refresh=True` tells HTMX to
    reload the current page in place (PUT on a state-axis subresource —
    activation flipped, re-render so the affordances update). Mutually
    exclusive — set one.
    """
    if (hx_redirect is None) == (not hx_refresh):
        raise ValueError(
            "updated_response requires exactly one of hx_redirect or hx_refresh"
        )
    headers = (
        {"HX-Redirect": hx_redirect}
        if hx_redirect is not None
        else {"HX-Refresh": "true"}
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body or {},
        headers=headers,
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
