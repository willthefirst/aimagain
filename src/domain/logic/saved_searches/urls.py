"""Render a saved search's `filter_values` dict back into a `/posts?…` URL.

This is the "open" half of the saved-search round-trip and the reason
the model stores structured filters rather than a URL string: the
canonical shareable URL is *derived* here, on demand, so URL-syntax
churn (how multi-values serialize, the `/posts` path itself) never
touches stored data — only this function changes.

Serialization mirrors the active-filter query-string builder in
`src/framework/dispatch/mounts/list_.py::handle_list` (multi-value
filters repeat the param; empty / None / `[]` values are dropped), so a
saved search opens to exactly the URL the posts filter form would have
produced.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

# The post directory's list path. Kept as a module constant (not
# hardcoded at each call site) so a future `/posts` rename is one edit.
POSTS_PATH = "/posts"


def filter_query_pairs(filters: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Flatten a `filter_values` dict into urlencode-ready pairs.

    Multi-value filters (lists) fan out to one pair per value; empty /
    None / `[]` / `""` values are dropped (an absent param means "no
    filter on this dimension")."""
    pairs: list[tuple[str, str]] = []
    for name, value in (filters or {}).items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            for one in value:
                pairs.append((name, str(one)))
        else:
            pairs.append((name, str(value)))
    return pairs


def posts_url_for_filters(filters: dict[str, Any] | None) -> str:
    """`{"kind": "clinician_opening", "state": ["CA", "NY"]}` →
    ``/posts?kind=clinician_opening&state=CA&state=NY``. Empty filters →
    bare ``/posts`` (the whole directory)."""
    qs = urlencode(filter_query_pairs(filters))
    return f"{POSTS_PATH}?{qs}" if qs else POSTS_PATH
