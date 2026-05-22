"""Page navigation for list views.

`handle_list` (and bespoke list handlers like `handle_list_my_favorites`,
`handle_list_user_providers`) parse `?page=N` from the request, ask
the logic layer for `per_page + 1` rows, and slice the trailing probe
row off to compute `has_next` without a separate `COUNT(*)` query.

Per-entity page size lives on `EntitySpec.page_size`; unset entities
use `DEFAULT_PAGE_SIZE`. Bespoke handlers pass `per_page` explicitly
to `paginate(...)` since they don't go through a spec.

The view-type template `views/list.html` renders the
`_shared/pagination.html` macro from the `page_meta` context var.
Pages where the result fits on a single page render no controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar
from urllib.parse import parse_qsl, urlencode

from starlette.requests import Request

DEFAULT_PAGE_SIZE = 15

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    """Snapshot of a page of items inside a list view's template context.

    `views/list.html` renders `_shared/pagination.html` from this; the
    macro shows Prev / Page N / Next and emits nothing when neither
    `has_prev` nor `has_next` is true (single-page result).
    """

    page: int
    per_page: int
    has_prev: bool
    has_next: bool

    @property
    def prev_page(self) -> int:
        return max(1, self.page - 1)

    @property
    def next_page(self) -> int:
        return self.page + 1


def parse_page(request: Request) -> int:
    """Read `?page=N` from the request, clamp to >= 1, default to 1.

    Non-integer or out-of-range values silently default to 1 rather
    than 422-ing — the rest of the URL is still meaningful (filters,
    breadcrumb) and showing page 1 is a more useful fallback than an
    error page for what's typically a typo'd or stale link.
    """
    raw = request.query_params.get("page")
    if raw is None:
        return 1
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, page)


def offset_for(page: int, per_page: int) -> int:
    """Compute the SQL `OFFSET` for a 1-indexed page number."""
    return (page - 1) * per_page


def base_query(request: Request) -> str:
    """Return the request's query string with `page` stripped.

    The `_shared/pagination.html` macro appends `&page=N` (or
    `?page=N` when this is empty) to build links that preserve filter
    state across page navigation. Multi-value params (e.g. posts'
    `?state=NY&state=CA`) round-trip via `urlencode(..., doseq=True)`.
    """
    pairs = [(k, v) for k, v in parse_qsl(request.url.query) if k != "page"]
    return urlencode(pairs, doseq=True)


def paginate(
    items_plus_one: Sequence[T], *, page: int, per_page: int
) -> tuple[list[T], Page]:
    """Slice the `+1` probe result and build the `Page` snapshot.

    Callers ask the logic layer for `per_page + 1` rows; if that many
    came back, there's at least one more row on the next page
    (`has_next=True`). The trailing probe row is trimmed before the
    items reach the template.
    """
    has_next = len(items_plus_one) > per_page
    items = list(items_plus_one[:per_page])
    return items, Page(
        page=page,
        per_page=per_page,
        has_prev=page > 1,
        has_next=has_next,
    )
