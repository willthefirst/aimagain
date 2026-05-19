"""Tests for the generic view-type templates in ``src/framework/templates/views/``.

These templates wire the page chrome (breadcrumb + toolbar + content) by
convention so a domain template only declares what's unique to it. The
tests below pin the chrome contract by rendering each view-type template
with stub child templates and asserting the breadcrumb segments, toolbar
shape, and content block all land where the contract promises.

Domain-template-side coverage lives in the route tests (e.g.
``src/domain/routes/test_providers.py``); these tests cover the
view-type templates *in isolation* so a regression in the chrome shows
up here even if no domain template has been wired into it yet.
"""

from __future__ import annotations

import textwrap

from jinja2 import DictLoader, Environment, FileSystemLoader, select_autoescape
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    """Stand up a Jinja env layered over the framework templates root
    plus an in-memory dict loader for the child stubs each test defines.

    Uses ``ChoiceLoader`` semantics via two ``FileSystemLoader``s? No —
    Jinja's ``Environment`` only takes one loader. The dict loader for
    the stubs goes first; framework templates resolve through the
    fallback ``FileSystemLoader``. This is identical to how the real
    runtime resolves ``views/...`` from the framework root and
    ``providers/list.html`` from the domain root.
    """
    from jinja2 import ChoiceLoader

    framework_loader = FileSystemLoader("src/framework/templates")
    # Per-test stub child templates go in the DictLoader the caller
    # populates via ``env.loader.loaders[0].mapping[...]``.
    stub_loader = DictLoader({})
    env = Environment(
        loader=ChoiceLoader([stub_loader, framework_loader]),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # `base.html` references the `entity_url` / `entity_form_url`
    # Jinja globals registered in production by
    # `src.framework.rendering.templating`. Mirror them here so the
    # chrome renders without needing a full app boot.
    from src.framework.rendering.route_urls import entity_form_url, entity_url

    env.globals["entity_url"] = entity_url
    env.globals["entity_form_url"] = entity_form_url
    return env


def _add_child(env: Environment, name: str, body: str) -> None:
    env.loader.loaders[0].mapping[name] = textwrap.dedent(body).lstrip()


def test_list_view_renders_single_segment_breadcrumb() -> None:
    """``views/list.html`` fills the `breadcrumb` block with a
    single-segment `breadcrumb([(resource_label, None)])` call. The
    child only declares the label."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Providers{% endblock %}
        {% block content %}<div id="body">ok</div>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    # Single-segment breadcrumb: the label appears inside the
    # `<nav aria-label="breadcrumb">` strip with `aria-current="page"`
    # (no `<a>` for the trailing segment).
    assert 'aria-label="breadcrumb"' in html
    assert 'aria-current="page"' in html
    assert "Providers" in html
    # Content block lands in the page body.
    assert '<div id="body">ok</div>' in html


def test_list_view_omits_toolbar_when_no_filters_no_actions() -> None:
    """The toolbar shell renders only when filters or actions are
    present — empty pages don't emit a stray `<hr />`."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Users{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    # Parse rather than substring-match: `base.html`'s CSS comment
    # references `<div class="toolbar">` verbatim to document the
    # shape, so a naive `in html` check would false-positive.
    tree = HTMLParser(html)
    assert tree.css_first("div.toolbar") is None


def test_list_view_renders_actions_block_in_toolbar_right() -> None:
    """A child that fills `{% block actions %}` gets its content in the
    toolbar's right zone, which is a `<menu>` of `<li>` commands."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block actions %}<li><a id="create" href="/posts/form">Create</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    assert '<li><a id="create" href="/posts/form">Create</a></li>' in html


def test_detail_view_renders_two_segment_breadcrumb_and_actions() -> None:
    """``views/detail.html`` builds `[(resource_label, resource_url),
    (current_label, None)]` and renders actions inside the shared
    two-zone toolbar — empty left zone (no search link), and a
    `<menu class="toolbar-right">` carrying the `<li>` commands. Pins
    the "detail actions land at the same right edge as list-page
    actions" rule (no per-view-type toolbar shape)."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/detail.html" %}
        {% set resource_url = "/providers" %}
        {% block resource_label %}Providers{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block actions %}<li><a id="edit" href="/providers/1/form">Edit</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html and ">Providers</a>" in html
    assert "Sunrise Therapy" in html
    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    # No search link on detail pages — left zone stays empty.
    assert 'class="toolbar-filter-link"' not in html
    assert '<li><a id="edit" href="/providers/1/form">Edit</a></li>' in html


def test_form_new_view_appends_new_segment() -> None:
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_new.html" %}
        {% set resource_url = "/providers" %}
        {% block resource_label %}Providers{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html and ">Providers</a>" in html
    assert ">New</li>" in html or ">New<" in html
    assert '<form id="x"></form>' in html


def test_entity_card_header_wraps_on_narrow_viewports() -> None:
    """Regression for #577 — `.entity-card > header.entity-header` must
    set `flex-wrap: wrap` so the modality chip + right-aligned `<small>`
    date stay visible at ≤375px viewports. Without it the chip and date
    clip past the card's right edge on mobile."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    match = re.search(
        r"\.entity-card\s*>\s*header\.entity-header\s*\{[^}]*\}",
        html,
    )
    assert match is not None, "entity-header rule missing from base.html"
    assert "flex-wrap: wrap" in match.group(
        0
    ), "entity-header must set `flex-wrap: wrap` to avoid #577 clipping"


def test_index_table_rows_stack_on_narrow_viewports() -> None:
    """Regression for #578 — every `index_table` row whose `<td>` cells
    carry `data-label` must stack into "Label: value" lines on ≤640px
    viewports so off-screen columns (e.g. `/providers` Insurance) stay
    visible without horizontal scroll. Pin the CSS rule's presence by
    matching the stacking rules under a `max-width: 640px` `@media`
    block scoped to `.overflow-auto table[role="grid"]`."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Providers{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    # Two `@media (max-width: 640px)` blocks exist in base.html (the
    # entity-grid collapse and this one); concatenate every match body
    # and assert the stacking rules appear in at least one. Bespoke
    # tables (organizations/programs) that don't emit `data-label`
    # stay on the horizontal-scroll path because the rules scope to
    # `.overflow-auto table[role="grid"] td[data-label]`.
    all_640_blocks = re.findall(
        r"@media\s*\(\s*max-width:\s*640px\s*\)\s*\{(.*?)\n      \}",
        html,
        re.DOTALL,
    )
    assert all_640_blocks, "no @media (max-width: 640px) block in base.html"
    combined = "\n".join(all_640_blocks)
    assert (
        '.overflow-auto table[role="grid"] thead' in combined
    ), "missing thead hide rule for responsive index-table stacking"
    assert (
        "td[data-label]" in combined
    ), "missing td[data-label] rule for responsive index-table stacking"
    assert (
        "content: attr(data-label)" in combined
    ), "missing data-label ::before content rule"


def test_in_cell_action_menu_lays_out_inline() -> None:
    """Regression for #580 — `<menu>` inside a table cell must render
    its `<li>` commands inline (single-line cluster), not stacked. The
    `/users` table's Actions cell had Deactivate/Reactivate + Delete
    stacking vertically and doubling row height. Scoping to `td >
    menu` (not all `<menu>`) keeps the page toolbar `<menu>`
    untouched."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Users{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )
    match = re.search(
        r"td\s*>\s*menu\s*\{[^}]*\}",
        html,
    )
    assert match is not None, "missing `td > menu` rule in base.html"
    assert "display: flex" in match.group(
        0
    ), "`td > menu` must use flex layout so `<li>` commands sit inline (#580)"


def test_entity_facts_dl_uses_two_column_grid_on_desktop() -> None:
    """Regression for #586 — `.entity-card > section.entity-facts > dl`
    must render in a 2-column grid on ≥768px viewports so the facts
    list doesn't waste 60–70% of the card's horizontal space. The rule
    targets `entity-facts` as a *direct child* of `entity-card`, so
    post-detail (where `entity-facts` sits inside `.entity-grid`'s
    right column) keeps its single-column layout."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )
    match = re.search(
        r"@media\s*\(\s*min-width:\s*768px\s*\)\s*\{[^@]*?"
        r"\.entity-card\s*>\s*section\.entity-facts\s*>\s*dl\s*\{[^}]*\}",
        html,
        re.DOTALL,
    )
    assert match is not None, (
        "missing `@media (min-width: 768px) { .entity-card > section.entity-facts > dl { ... } }` "
        "rule in base.html (#586)"
    )
    assert "grid-template-columns: 1fr 1fr" in match.group(
        0
    ), "entity-facts dl must use 2-column grid on desktop"


def test_form_edit_view_renders_three_segment_breadcrumb() -> None:
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_edit.html" %}
        {% set resource_url = "/providers" %}
        {% set resource_detail_url = "/providers/42" %}
        {% block resource_label %}Providers{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html
    assert 'href="/providers/42"' in html
    assert "Sunrise Therapy" in html
    assert ">Edit</li>" in html or ">Edit<" in html


def test_destructive_action_macros_emit_danger_class() -> None:
    """Regression for #579 — every Delete affordance must carry
    `class="danger"` (defined in base.html). Pins the two macros that
    own the destructive-button vocabulary:

    1. `_shared/actions.html::confirm_delete_button` — used by toolbar
       owner/admin actions and inline subentity rows.
    2. `_shared/forms.html::form_actions` — the standard
       Save/Cancel/Delete cluster at the bottom of every entity form.
    """
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% from "_shared/actions.html" import confirm_delete_button %}
        {% from "_shared/forms.html" import form_actions %}
        <div id="toolbar-delete">
          {{ confirm_delete_button("/posts/1", "Sure?") }}
        </div>
        <div id="form-delete">
          {{ form_actions("Save", cancel_url="/posts/1", delete_url="/posts/1", delete_confirm="Sure?") }}
        </div>
        """,
    )
    html = env.get_template("stub.html").render()

    tree = HTMLParser(html)
    toolbar = tree.css_first("#toolbar-delete button")
    assert toolbar is not None
    assert "danger" in (
        toolbar.attributes.get("class") or ""
    ), "confirm_delete_button must emit class containing 'danger'"

    form_delete = tree.css_first("#form-delete .form-actions-destructive")
    assert form_delete is not None
    assert "danger" in (
        form_delete.attributes.get("class") or ""
    ), "form_actions Delete button must emit class containing 'danger'"


def test_form_actions_cancel_uses_secondary_outline() -> None:
    """Regression for #599 — the canonical Cancel affordance on every
    entity create/edit form must render with `class="secondary outline"`
    (the project's single "secondary" role per the 4-role vocabulary in
    `base.html` and the framework README). Without this pin, Cancel
    could drift back to bare `.outline` (blue-outlined) and break
    consistency with Cancel buttons elsewhere."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% from "_shared/forms.html" import form_actions %}
        <div id="cluster">
          {{ form_actions("Save", cancel_url="/orgs/1") }}
        </div>
        """,
    )
    html = env.get_template("stub.html").render()
    tree = HTMLParser(html)
    cancel = tree.css_first('#cluster a[role="button"]')
    assert cancel is not None
    classes = (cancel.attributes.get("class") or "").split()
    assert "secondary" in classes and "outline" in classes, (
        "form_actions Cancel must emit class='secondary outline' "
        f"(got {cancel.attributes.get('class')!r})"
    )


def test_search_view_clear_uses_tertiary_class() -> None:
    """Regression for #599 — Clear next to Apply on the search page must
    render with `class="tertiary"` (text-only link-button). Pre-#599 it
    used `class="secondary"` (filled gray), which read as a third
    full-weight button competing with Apply."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/search.html" %}
        {% block resource_label %}Posts{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        list_action="/posts",
        declared_filters=[],
        filter_values={},
    )
    tree = HTMLParser(html)
    clear = None
    for a in tree.css('a[role="button"]'):
        if (a.text() or "").strip() == "Clear":
            clear = a
            break
    assert clear is not None, "search.html must render a Clear link-button"
    classes = (clear.attributes.get("class") or "").split()
    assert "tertiary" in classes, (
        "Clear must emit class containing 'tertiary' "
        f"(got {clear.attributes.get('class')!r})"
    )


def test_base_html_defines_tertiary_button_style() -> None:
    """Regression for #599 — `.tertiary` button style must be defined in
    base.html so `class="tertiary"` renders as a text-only link-button.
    Without this rule the class is a no-op and Clear falls back to
    Pico's filled primary."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )
    match = re.search(
        r"button\.tertiary,[^{]*\{[^}]*background-color:\s*transparent[^}]*\}",
        html,
        re.DOTALL,
    )
    assert (
        match is not None
    ), "base.html must define `button.tertiary` with transparent background"


def test_base_html_defines_danger_button_style() -> None:
    """Regression for #579 — `.danger` button style must be defined in
    base.html with a red token. Without it, `class="danger"` falls back
    to Pico's primary blue and the destructive button looks like the
    page's main CTA."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )
    match = re.search(
        r"button\.danger,[^{]*\{[^}]*--pico-color-red-[^}]*\}",
        html,
        re.DOTALL,
    )
    assert (
        match is not None
    ), "base.html must define `button.danger` with a Pico red token"


class _RequestStub:
    """Minimal stand-in for the FastAPI ``Request`` that `base.html`
    references via `request.url.path` in the primary-nav section."""

    class _Url:
        path = "/"

    url = _Url()
    # `base.html` reads `request.query_params.get('kind')` to highlight
    # the section-shortcut links; an empty mapping mirrors the no-query
    # case for view-template unit tests.
    query_params: dict[str, str] = {}


def _request_stub() -> _RequestStub:
    return _RequestStub()
