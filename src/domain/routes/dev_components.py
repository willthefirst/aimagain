"""Dev-only component gallery route.

``GET /dev/components``
    Renders every framework and domain component (Jinja macros, CSS
    classes) with fixture data so they can be inspected and iterated in
    isolation — no database, no login required.

Only mounted when ``ENVIRONMENT == "development"``.  Same double-guard
as ``dev_auth.py``: the router is excluded from production at mount
time and each handler raises 404 if the env flag drifts.
"""

from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from src.framework.config import settings
from src.framework.http.responses import APIResponse

router = APIRouter(tags=["dev"])


def _fixture_page_meta():
    return SimpleNamespace(
        page=2,
        total_pages=5,
        per_page=20,
        has_prev=True,
        has_next=True,
        prev_page=1,
        next_page=3,
    )


@router.get("/dev/components")
async def component_gallery(request: Request):
    """Render every macro and CSS component with fixture data."""
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=404)

    context = {
        "fixture_page_meta": _fixture_page_meta(),
        "fixture_choices": [
            ("opt1", "Option one"),
            ("opt2", "Option two"),
            ("opt3", "Option three"),
            ("opt4", "Option four"),
        ],
        "fixture_icon_list": [
            {"icon": "map-pin", "label": "San Francisco, CA"},
            {"icon": "shield-check", "label": "LCSW"},
            {"icon": "graduation-cap", "label": "University of California"},
            {"icon": "baby", "label": "Children and adolescents"},
        ],
        "fixture_breadcrumb": [
            {"label": "Clinicians", "href": "/clinicians"},
            {"label": "Dr. Jane Smith", "href": None},
        ],
    }

    return APIResponse.html_response(
        template_name="dev/components.html",
        context=context,
        request=request,
        current_user=None,
    )


def mount_dev_components(app, *, environment: str) -> None:
    """Mount the component gallery iff ``environment`` is ``"development"``."""
    if environment == "development":
        app.include_router(router)
