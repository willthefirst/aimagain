"""Render-time contract enforcement for the framework's view-type templates.

The view-type templates under [`../templates/views/`](../templates/views/)
each read a fixed set of context keys at the top level (before any
optional block override). Any template that `{% extends "views/X.html"
%}` inherits that contract — its handler must inject the same keys, or
the render crashes with an `UndefinedError` deep in a chrome block.

That's the silent-coupling class issue #1271 captures. Two real
demonstrations:

- `mount_search` and the bespoke `/users/me/email/form` route shipped
  without `entity_name` in context; the breadcrumb's
  `breadcrumb_entity_item(entity_name)` call (added in #1269) blew up
  at render. Caught only when chrome tests exercised them.

- Four contract-test stubs in `tests/test_contract/infrastructure/`
  rendered view-type templates directly, also without `entity_name`.
  Caught only when CI ran the contract suite on #1269.

The fix is one validator: when `APIResponse.html_response` is asked to
render a template, walk the `{% extends %}` chain back to its
view-type parent and assert every required key is in the merged
context. A handler that forgets a key surfaces at the first render
with a clear, actionable error instead of a stack trace into Jinja
internals.

The required-keys table lives here (not in each template's docstring)
so it's a single Python value tests can import and assertions can run
against. The matching docstring sections in
[`../templates/views/`](../templates/views/) describe the same
contract for template readers; both stay in sync because this module's
test exercises every entry against the live template source.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterable

# Per view-type template: tuple of context-key names that the chrome
# reads unconditionally (no `is defined` / `| default` guard around the
# access). Templates that extend a view-type inherit these requirements.
#
# Keep the table flat — one tuple per view type — and the keys
# alphabetized within each tuple so a future addition is a single line
# in one obvious place.
VIEW_TYPE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "views/detail.html": ("entity_name",),
    "views/form_new.html": ("create_heading", "entity_name"),
    "views/form_edit.html": (
        "edit_heading",
        "entity_name",
        "resource_detail_url",
    ),
    # Sub-resource form templates extend their plain `form_{new,edit}.html`
    # parent — the validator walks one `{% extends %}` hop, so rendering
    # `views/subresource_form_new.html` directly resolves to the parent's
    # requirements (create_heading + entity_name). The only key the
    # subresource template adds on top is `form_partial`, which it
    # `{% include %}`s — that's what the entries below pin against drift.
    "views/subresource_form_new.html": ("form_partial",),
    "views/subresource_form_edit.html": ("form_partial",),
    "views/search.html": (
        "declared_filters",
        "entity_name",
        "filter_heading",
        "filter_values",
        "list_action",
    ),
    "views/list.html": (),  # All chrome access is guarded by `is defined`.
}

# Matches `{% extends "views/X.html" %}` (single or double quote, any
# whitespace). The view-type templates extend `base.html` so they end
# the chain — the validator stops at the first `views/*` hit.
_EXTENDS_VIEW_TYPE_RE = re.compile(
    r"""\{%\s*extends\s+["'](views/[^"']+\.html)["']\s*%\}"""
)


@lru_cache(maxsize=None)
def view_type_for(template_name: str) -> str | None:
    """Return the `views/X.html` parent for `template_name`, or `None`
    when the template doesn't extend a view-type (auth pages,
    `landing.html`, `dev/components.html`, etc.).

    Resolved by reading the template source and matching the
    `{% extends %}` directive — Jinja's AST has a typed `nodes.Extends`
    walker but a regex match on a top-of-file directive is enough and
    avoids a second parse pass per render.

    Cached because the answer is determined by the template source on
    disk; it doesn't vary per request. In dev `auto_reload=True` reloads
    templates when their source changes — the cache is intentionally
    *not* invalidated alongside that (rare during a dev session; the
    operator restarts to pick up structural changes).
    """
    from src.framework.rendering.templating import _env

    try:
        source, _, _ = _env.loader.get_source(_env, template_name)
    except Exception:
        # Template not resolvable (typo, lookup failure) — the
        # downstream `TemplateResponse` call will raise its own
        # `TemplateNotFound`. Returning `None` here lets that path
        # surface unchanged.
        return None
    m = _EXTENDS_VIEW_TYPE_RE.search(source)
    return m.group(1) if m else None


def missing_required_keys(
    template_name: str, merged_context: dict[str, Any]
) -> list[str]:
    """Return the sorted list of required keys absent from `merged_context`
    for the view-type chrome inherited by `template_name`. Empty list
    when the template has no view-type parent or every key is present —
    the caller treats empty as "render is safe."
    """
    view_type = view_type_for(template_name)
    if view_type is None:
        return []
    required: Iterable[str] = VIEW_TYPE_REQUIREMENTS.get(view_type, ())
    return sorted(k for k in required if k not in merged_context)


class ViewTypeContextError(ValueError):
    """Raised when a render is missing a required view-type context key.

    A `ValueError` subclass so existing `except ValueError` handlers
    (none today, but future-proof) treat it as a programmer error rather
    than something a request body can trigger."""


def assert_view_type_context(
    template_name: str, merged_context: dict[str, Any]
) -> None:
    """Raise `ViewTypeContextError` if `merged_context` is missing any
    key the view-type chrome requires. Called once per render from
    `APIResponse.html_response` — the cost is one cached regex lookup
    plus a dict-membership check per required key (small, fixed).

    The error message names the template, the inherited view-type, and
    every missing key so the fix is a one-line context-dict edit.
    """
    missing = missing_required_keys(template_name, merged_context)
    if not missing:
        return
    view_type = view_type_for(template_name)
    required = VIEW_TYPE_REQUIREMENTS.get(view_type or "", ())
    raise ViewTypeContextError(
        f"Render of {template_name!r} (extends {view_type!r}) is "
        f"missing required context key(s): {missing}. "
        f"View-type {view_type!r} requires: {list(required)}. "
        f"Inject the missing key(s) in the handler's `context=` "
        f"dict — see src/framework/rendering/view_type_contract.py "
        f"for the table and src/framework/templates/views/ docstrings "
        f"for what each key carries."
    )
