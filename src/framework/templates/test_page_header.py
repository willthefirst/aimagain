"""Tests for the unified page-header band (``_shared/_page_header.html``).

The band is the single fixed top-chrome element: primary nav + breadcrumb
slot + toolbar slot + one boundary ``<hr>``. These tests render the generic
view-type templates (which compose the band via ``base.html``) and pin the
band's structure — the toolbar ``<h1>`` and breadcrumb live *inside*
``header.page-header``, the breadcrumb row is reserved with a placeholder on
list pages (so the rule sits at a constant Y), and exactly one ``<hr>``
exists (in the band, none in ``<main>``).

A second group pins the CSS rules the constant-boundary + no-wrap
guarantees depend on, mirroring the regex-against-``framework.css`` style in
``test_views.py``.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
)
from selectolax.parser import HTMLParser

_CSS_PATH = Path(__file__).parent.parent / "static" / "css" / "framework.css"


def _make_env() -> Environment:
    framework_loader = FileSystemLoader("src/framework/templates")
    stub_loader = DictLoader({})
    env = Environment(
        loader=ChoiceLoader([stub_loader, framework_loader]),
        autoescape=select_autoescape(["html", "xml"]),
    )
    from src.framework.rendering.labels import (
        entity_create_label,
        entity_filter_label,
    )
    from src.framework.rendering.route_urls import entity_form_url, entity_url

    env.globals["entity_url"] = entity_url
    env.globals["entity_form_url"] = entity_form_url
    env.globals["entity_create_label"] = entity_create_label
    env.globals["entity_filter_label"] = entity_filter_label
    return env


def _add_child(env: Environment, name: str, body: str) -> None:
    env.loader.loaders[0].mapping[name] = textwrap.dedent(body).lstrip()


class _RequestStub:
    class _Url:
        path = "/"

    url = _Url()
    query_params: dict[str, str] = {}


def _request_stub(path: str = "/") -> _RequestStub:
    stub = _RequestStub()
    stub.url = _RequestStub._Url()
    stub.url.path = path
    stub.query_params = {}
    return stub


def _render(env: Environment, name: str, **ctx: object) -> str:
    base: dict[str, object] = dict(
        request=_request_stub(), is_authenticated=False, is_development=False
    )
    base.update(ctx)
    return env.get_template(name).render(**base)


_DETAIL_STUB = """
    {% extends "views/detail.html" %}
    {% set resource_url = "/clinicians" %}
    {% block resource_label %}Clinicians{% endblock %}
    {% block current_label %}Sunrise Therapy{% endblock %}
    {% block content %}<p>body</p>{% endblock %}
"""

_LIST_STUB = """
    {% extends "views/list.html" %}
    {% block resource_label %}Clinicians{% endblock %}
    {% block content %}<p>body</p>{% endblock %}
"""


def test_detail_toolbar_h1_and_breadcrumb_live_inside_the_band() -> None:
    """A detail page's page title (`<h1>`) and breadcrumb both render
    *inside* `header.page-header` — the band owns the whole top chrome, not
    just the nav. The real breadcrumb means no reserved placeholder."""
    env = _make_env()
    _add_child(env, "stub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "stub.html"))

    assert tree.css_first("header.page-header div.toolbar h1") is not None
    assert tree.css_first('header.page-header nav[aria-label="breadcrumb"]') is not None
    # A real breadcrumb is present, so the reserved placeholder is absent.
    assert tree.css_first(".page-header-crumb-placeholder") is None


def test_list_reserves_breadcrumb_row_with_hidden_placeholder() -> None:
    """List pages carry no real breadcrumb, but the band still reserves the
    breadcrumb row with a hidden placeholder so the boundary rule sits at
    the same Y as a detail page's. The toolbar `<h1>` still lives in the
    band."""
    env = _make_env()
    _add_child(env, "stub.html", _LIST_STUB)
    tree = HTMLParser(_render(env, "stub.html"))

    # No real breadcrumb on list pages...
    assert tree.css_first('header.page-header nav[aria-label="breadcrumb"]') is None
    # ...but the row is reserved with the placeholder.
    assert (
        tree.css_first("header.page-header .page-header-crumb-placeholder") is not None
    )
    assert tree.css_first("header.page-header div.toolbar h1") is not None


def test_band_owns_the_single_boundary_rule_and_main_has_none() -> None:
    """Exactly one `<hr>` exists and it lives in the band (carrying the
    `page-header-rule` class); `<main>` has none. The toolbar macro no
    longer emits its own separator — the band owns the single divider."""
    env = _make_env()
    _add_child(env, "stub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "stub.html"))

    band = tree.css_first("header.page-header")
    assert band is not None
    assert len(band.css("hr")) == 1
    assert band.css_first("hr.page-header-rule") is not None

    main = tree.css_first("main")
    assert main is not None
    assert len(main.css("hr")) == 0


def test_every_toolbar_reserves_the_action_row_height() -> None:
    """Each toolbar renders a hidden, non-interactive reserve `<button>` so
    the action-row height (and thus the band boundary's Y) is constant
    whether or not a page has real actions. Pinned on an action-free list
    stub and an action-bearing detail stub; the reserve is aria-hidden and
    removed from the tab order so it's chrome-only."""
    env = _make_env()
    _add_child(env, "liststub.html", _LIST_STUB)
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    for name in ("liststub.html", "detailstub.html"):
        tree = HTMLParser(_render(env, name))
        reserve = tree.css_first(
            "header.page-header div.toolbar button.toolbar-reserve"
        )
        assert reserve is not None, f"{name}: toolbar must render the reserve button"
        assert reserve.attributes.get("aria-hidden") == "true"
        assert reserve.attributes.get("tabindex") == "-1"


def test_css_pins_no_wrap_truncation_and_reserved_band() -> None:
    """Pin the CSS the band's guarantees rest on: the actions cells never
    wrap (so they don't grow the band), the toolbar `<h1>` truncates rather
    than wraps (constant one-line heading), and the breadcrumb placeholder
    reserves its row via `visibility: hidden` (intrinsic height, no pinned
    size unit)."""
    css = _CSS_PATH.read_text()

    assert re.search(
        r"\.toolbar-actions[^{]*\{[^}]*flex-wrap:\s*nowrap", css, re.DOTALL
    ), ".toolbar-actions must declare `flex-wrap: nowrap` so actions don't grow the band"
    assert re.search(
        r"\.toolbar-right\b[^{]*\{[^}]*flex-wrap:\s*nowrap", css, re.DOTALL
    ), ".toolbar-right must declare `flex-wrap: nowrap`"

    h1_rule = re.search(r"\.toolbar\s+h1\s*\{([^}]*)\}", css, re.DOTALL)
    assert h1_rule is not None, ".toolbar h1 must have a rule"
    h1_body = h1_rule.group(1)
    for decl in ("text-overflow: ellipsis", "white-space: nowrap", "min-width: 0"):
        assert (
            decl in h1_body
        ), f".toolbar h1 must declare `{decl}` so the title truncates"

    assert re.search(
        r"\.page-header-crumb-placeholder\s*\{[^}]*visibility:\s*hidden", css, re.DOTALL
    ), ".page-header-crumb-placeholder must reserve its row via `visibility: hidden`"

    # The action-row reserve: a hidden button sharing the H1's grid cell.
    # Both the H1 and the reserve must be pinned to row 1 / col 1 so the
    # reserve overlaps the H1 (instead of being pushed to a second row) and
    # the actions cell still auto-flows for the mobile stack.
    h1_grid = re.search(r"\.toolbar\s+h1\s*\{([^}]*)\}", css, re.DOTALL).group(1)
    assert "grid-row: 1" in h1_grid and "grid-column: 1" in h1_grid, (
        ".toolbar h1 must be explicitly placed at row 1 / col 1 so the reserve "
        "button overlaps it"
    )
    reserve_rule = re.search(r"\.toolbar-reserve\s*\{([^}]*)\}", css, re.DOTALL)
    assert reserve_rule is not None, ".toolbar-reserve must have a rule"
    reserve_body = reserve_rule.group(1)
    for decl in ("grid-row: 1", "grid-column: 1", "visibility: hidden"):
        assert decl in reserve_body, f".toolbar-reserve must declare `{decl}`"
