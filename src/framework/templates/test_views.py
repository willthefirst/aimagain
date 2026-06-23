"""Tests for the generic view-type templates in ``src/framework/templates/views/``.

These templates wire the page chrome (breadcrumb + toolbar + content) by
convention so a domain template only declares what's unique to it. The
tests below pin the chrome contract by rendering each view-type template
with stub child templates and asserting the breadcrumb segments, toolbar
shape, and content block all land where the contract promises.

Domain-template-side coverage lives in the route tests (e.g.
``src/domain/routes/test_clinicians.py``); these tests cover the
view-type templates *in isolation* so a regression in the chrome shows
up here even if no domain template has been wired into it yet.
"""

from __future__ import annotations

from types import SimpleNamespace

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.framework.templates._test_env import add_child as _add_child
from src.framework.templates._test_env import make_test_env as _make_env_impl


def _make_env() -> Environment:
    """Stand up a Jinja env layered over the framework templates root
    plus an in-memory dict loader for the child stubs each test defines.

    Thin wrapper over `_test_env.make_test_env()`: mirrors the prod
    globals snapshot so a new Jinja global registered in `templating.py`
    flows here without an extra edit. Test bodies still poke per-test
    stubs via `_add_child(env, name, body)`.
    """
    return _make_env_impl()


def test_list_view_renders_h1_in_toolbar_and_home_breadcrumb() -> None:
    """``views/list.html`` puts the `resource_label` into the toolbar `<h1>`
    (the page title) and, for an authenticated viewer, renders the breadcrumb
    as `Home › <collection>` — the collection itself is the current (unlinked)
    leaf. The child only declares the label."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block content %}<div id="body">ok</div>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_development=False,
    )

    tree = HTMLParser(html)
    crumbs = tree.css('nav[aria-label="breadcrumb"] ul li')
    assert [li.text(strip=True) for li in crumbs] == ["Home", "Clinicians"]
    assert crumbs[-1].css_first("a") is None  # collection is the current page
    # The heading lives in the toolbar `<h1>`.
    toolbar_h1 = tree.css_first("div.toolbar h1")
    assert toolbar_h1 is not None
    assert toolbar_h1.text(strip=True) == "Clinicians"
    # Content block lands in the page body.
    assert '<div id="body">ok</div>' in html


def test_list_view_renders_auto_breadcrumb_when_items_injected() -> None:
    """When the mount injects ``_breadcrumb_items`` into the context,
    ``views/list.html`` renders the full chain automatically — no
    per-template ``{% block breadcrumb %}`` needed. Home is prepended; each
    injected segment with an href links; the trailing href-less segment is
    the current page."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block content %}<div id="body">ok</div>{% endblock %}
        """,
    )

    items = [
        ("Users", "/users"),
        ("will", "/users/me"),
        ("Clinicians", None),
    ]
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_development=False,
        _breadcrumb_items=items,
    )

    tree = HTMLParser(html)
    crumbs = tree.css('nav[aria-label="breadcrumb"] ul li')
    assert [li.text(strip=True) for li in crumbs] == [
        "Home",
        "Users",
        "will",
        "Clinicians",
    ]
    assert crumbs[2].css_first("a").attributes.get("href") == "/users/me"
    assert crumbs[-1].css_first("a") is None  # current page, no link


def test_anonymous_pages_omit_the_breadcrumb_band() -> None:
    """Breadcrumbs are authenticated-app chrome: an anonymous viewer gets no
    breadcrumb band at all (bare brand nav only), even on a page whose
    breadcrumb block would otherwise produce a chain."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    tree = HTMLParser(html)
    assert tree.css_first('nav[aria-label="breadcrumb"]') is None


def test_list_view_renders_toolbar_with_h1_even_without_actions() -> None:
    """The toolbar shell always renders on list pages now because
    it owns the page `<h1>`; previously it was suppressed when
    neither filter link nor actions were present. The shell still
    renders cleanly with the heading alone."""
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

    tree = HTMLParser(html)
    toolbar = tree.css_first("div.toolbar")
    assert toolbar is not None
    h1 = toolbar.css_first("h1")
    assert h1 is not None and h1.text(strip=True) == "Users"
    # No filter link and no action menu when child opts out.
    assert toolbar.css_first("a.toolbar-filter-link") is None
    assert toolbar.css_first("menu.toolbar-right") is None


def test_list_view_never_renders_filter_link_in_toolbar() -> None:
    """Filters live in the sidebar, never in the toolbar — even
    when `search_url` and active filters are populated in context
    (i.e. for an entity that declares `filters=(…)`). The toolbar
    carries only the `<h1>` and the optional action `<menu>`. Pins
    the structural rule so a future change can't quietly re-add a
    toolbar filter link by re-introducing `search_url` as a
    `page_toolbar` arg."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block list_body %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        # A spec with filters injects all of these — the toolbar
        # still must not render a filter link from any of them.
        filters=({"name": "kind", "label": "Type"},),
        filter_values={"kind": "x"},
        active_filters=[{"name": "kind", "value": "x", "label": "Type: X"}],
        active_filter_count=1,
        search_url="/clinicians/search?kind=x",
        filter_heading="Filter clinicians",
    )

    tree = HTMLParser(html)
    toolbar = tree.css_first("div.toolbar")
    assert toolbar is not None
    assert toolbar.css_first("a.toolbar-filter-link") is None
    # The search link is not in the sidebar (it moved to the results
    # column's summary header) and never in the toolbar.
    sidebar = tree.css_first("aside.filter-sidebar")
    assert sidebar is not None
    assert sidebar.css_first("hgroup a") is None
    # The sidebar carries no heading — the form sits directly in the <aside>.
    assert sidebar.css_first("header h2") is None
    summary = tree.css_first(".browse-results > header")
    assert summary is not None
    # With one active filter, the count ("1 filter") is the link to search.
    summary_link = summary.css_first("a")
    assert summary_link is not None
    assert summary_link.attributes.get("href") == "/clinicians/search?kind=x"
    assert summary_link.text(strip=True) == "1 filter"
    assert "Showing results with" in summary.text()


def test_filter_summary_reads_all_results_when_no_active_filters() -> None:
    """With a filtered entity but no active selection, the results-column
    summary header reads "Showing all results." with no count link."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block list_body %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        filters=({"name": "kind", "label": "Type"},),
        filter_values={},
        active_filters=[],
        active_filter_count=0,
        search_url="/clinicians/search",
        filter_heading="Filter clinicians",
    )

    tree = HTMLParser(html)
    summary = tree.css_first(".browse-results > header")
    assert summary is not None
    label = summary.css_first("p")
    assert label is not None and label.text(strip=True) == "Showing all results."
    # No filters active → no count link to the search page.
    assert summary.css_first("a") is None


def test_list_view_wraps_each_sidebar_filter_in_a_folded_accordion() -> None:
    """Each declared filter in the browse sidebar is wrapped in a Pico
    accordion (`<details class="filter-accordion">`) that starts folded
    (no `open` attribute) with the filter's `display_label` as its
    `<summary>`. The macro is called with `heading=false` so the inner
    fieldset doesn't repeat the title as a `<legend>`."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block list_body %}body{% endblock %}
        """,
    )

    filters = (
        SimpleNamespace(
            kind="choice",
            name="license_type",
            display_label="License type",
            multi=True,
            radio=False,
            choices=(("psyd", "PsyD"),),
        ),
        SimpleNamespace(
            kind="text",
            name="keyword",
            display_label="Keyword",
            placeholder=None,
        ),
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        filters=filters,
        filter_values={},
    )

    tree = HTMLParser(html)
    sidebar = tree.css_first("aside.filter-sidebar")
    assert sidebar is not None
    accordions = sidebar.css("details.filter-accordion")
    assert len(accordions) == len(filters), "one accordion per declared filter"
    # Folded by default — none carry the `open` attribute.
    assert all("open" not in a.attributes for a in accordions)
    summaries = [a.css_first("summary").text(strip=True) for a in accordions]
    assert summaries == ["License type", "Keyword"]
    # An <hr /> divides adjacent accordions — one fewer than the filter count,
    # so the last accordion has no trailing rule.
    assert len(sidebar.css("hr")) == len(filters) - 1
    # Heading suppressed inside the accordion: the multi-choice fieldset
    # renders without a `<legend>` (the summary already names the section).
    fieldset = sidebar.css_first("fieldset.search-checkbox-fieldset")
    assert fieldset is not None
    assert fieldset.css_first("legend") is None


def test_list_view_opens_accordion_for_active_filters_only() -> None:
    """An accordion renders `open` when its filter is in a dirty (active)
    state — `filter_values` holds a non-empty value for it — so applied
    filters stay visible on reload. Filters with no value (absent, empty
    string, or empty list) stay folded."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block list_body %}body{% endblock %}
        """,
    )

    filters = (
        SimpleNamespace(
            kind="choice",
            name="license_type",
            display_label="License type",
            multi=True,
            radio=False,
            choices=(("psyd", "PsyD"),),
        ),
        SimpleNamespace(
            kind="text",
            name="keyword",
            display_label="Keyword",
            placeholder=None,
        ),
        SimpleNamespace(
            kind="text",
            name="city",
            display_label="City",
            placeholder=None,
        ),
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        filters=filters,
        # license_type active (non-empty list), keyword active (non-empty
        # string), city inactive (empty string treated as no value).
        filter_values={"license_type": ["psyd"], "keyword": "ptsd", "city": ""},
    )

    tree = HTMLParser(html)
    accordions = tree.css("aside.filter-sidebar details.filter-accordion")
    open_state = {
        a.css_first("summary").text(strip=True): ("open" in a.attributes)
        for a in accordions
    }
    assert open_state == {"License type": True, "Keyword": True, "City": False}


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


def test_detail_view_renders_full_breadcrumb_and_actions() -> None:
    """``views/detail.html`` builds the full chain `Home › <collection> ›
    <resource>` — the collection links (via `breadcrumb_entity_item`) and the
    current resource (`current_label`) is the unlinked leaf. Actions land
    inside the shared two-zone toolbar — empty left zone (no search link), and
    a `<menu class="toolbar-right">` carrying the `<li>` commands. Uses `post`
    (no `read_policy`) so the collection link stays unlocked; the locked
    branch is pinned by `test_breadcrumb.py` / route-level tests."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/detail.html" %}
        {% set entity_name = "post" %}
        {% block resource_label %}Posts{% endblock %}
        {% block current_label %}A referral{% endblock %}
        {% block actions %}<li><a id="edit" href="/posts/1/form">Edit</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_development=False,
    )

    tree = HTMLParser(html)
    crumbs = tree.css('nav[aria-label="breadcrumb"] ul li')
    assert [li.text(strip=True) for li in crumbs] == ["Home", "Posts", "A referral"]
    assert crumbs[1].css_first("a").attributes.get("href") == "/posts"
    assert crumbs[-1].css_first("a") is None  # current resource, no link
    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    # No search link on detail pages — left zone stays empty.
    assert 'class="toolbar-filter-link"' not in html
    assert '<li><a id="edit" href="/posts/1/form">Edit</a></li>' in html


def test_form_new_view_renders_create_heading_from_context() -> None:
    """``views/form_new.html`` reads ``create_heading`` from the
    handler-supplied context and renders it as the toolbar `<h1>`.
    The handler computes it via `create_label_for(spec, kind=...)`,
    the same helper every "Create X" CTA reads from, so the page
    title can't drift from the button that opened it. Uses `post`
    (no `read_policy`) so the chrome assertion stays a plain unlocked
    back link — the locked branch is covered by
    `test_breadcrumb.py`."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_new.html" %}
        {% set entity_name = "post" %}
        {% block resource_label %}Posts{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_development=False,
        create_heading="Create post",
    )

    tree = HTMLParser(html)
    crumbs = tree.css('nav[aria-label="breadcrumb"] ul li')
    # Home › Posts › New — the collection links, `New` is the current leaf.
    assert [li.text(strip=True) for li in crumbs] == ["Home", "Posts", "New"]
    assert crumbs[1].css_first("a").attributes.get("href") == "/posts"
    assert crumbs[-1].css_first("a") is None
    assert "<h1>Create post</h1>" in html
    assert '<form id="x"></form>' in html


def test_primary_nav_excludes_non_journey_links_for_all_viewers() -> None:
    """The primary nav promotes only the unified `/posts` feed. Other
    URL families (`/clinicians` Directory, `/organizations`,
    `/programs`, `/users`) stay live and reachable by URL/bookmark but
    are intentionally absent from the chrome. Render twice (admin and
    non-admin) to pin that the `is_admin` branch doesn't reintroduce
    them either."""
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

    for is_admin_flag in (True, False):
        html = env.get_template("stub.html").render(
            request=_request_stub(),
            is_authenticated=True,
            is_admin=is_admin_flag,
            is_development=False,
        )
        tree = HTMLParser(html)
        nav_links = {
            a.attributes.get("href") for a in tree.css('nav[aria-label="Primary"] a')
        }
        # Brand → /home (the quicklinks hub); the posts feed family is
        # promoted via the `Post` link and the avatar's "My posts".
        assert "/home" in nav_links
        assert "/posts/form" in nav_links
        assert "/posts?owner=me" in nav_links
        # Non-journey families are NOT in the primary nav (regardless of
        # admin flag).
        for absent in (
            "/clinicians",
            "/organizations",
            "/programs",
            "/users",
        ):
            assert (
                absent not in nav_links
            ), f"{absent} must not appear in primary nav (is_admin={is_admin_flag})"


def test_form_edit_view_renders_breadcrumb_and_edit_heading() -> None:
    """``views/form_edit.html`` renders the full chain `Home › <collection> ›
    <resource> › Edit`: the collection links, the current resource links to
    its detail page (the ancestor of this edit form), and `Edit` is the
    unlinked leaf. The H1 reads the resource noun via `edit_heading`,
    mirroring the create-page contract where `create_heading` sources the
    H1."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_edit.html" %}
        {% set entity_name = "clinician" %}
        {% set resource_detail_url = "/clinicians/42" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_development=False,
        edit_heading="Edit clinician",
    )

    tree = HTMLParser(html)
    crumbs = tree.css('nav[aria-label="breadcrumb"] ul li')
    assert [li.text(strip=True) for li in crumbs] == [
        "Home",
        "Clinicians",
        "Sunrise Therapy",
        "Edit",
    ]
    # The resource links to its detail page (ancestor of the edit form).
    assert crumbs[2].css_first("a").attributes.get("href") == "/clinicians/42"
    assert crumbs[-1].css_first("a") is None  # `Edit` is the current page
    # H1 in the toolbar reads `edit_heading`, NOT "Edit <current_label>".
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None
    assert h1.text(strip=True) == "Edit clinician"


def test_actions_buttons_fill_row_width_on_desktop() -> None:
    """Save / Cancel must stretch (`flex: 1 1 0`) so the cluster fills
    the form's content width instead of clustering at the left edge as
    content-width flex items — without the rule the row visibly fell
    short of the form's right edge while every other element
    (fieldsets, inputs) filled the form. The Delete button keeps its
    content width (the `:not(.form-actions-destructive)` selector
    excludes it) and `margin-left: auto` pushes it to the far right.
    Pinned against `framework.css` so a future CSS edit that drops the
    grow rule fails here loudly."""
    import re
    from pathlib import Path

    css = (
        Path(__file__).parent.parent.parent
        / "framework"
        / "static"
        / "css"
        / "framework.css"
    ).read_text()
    # The non-destructive Save/Cancel rule must `flex: 1` (any
    # `1 1 0` / `1` variant) so they grow. Match the property
    # against any value that starts with `1`.
    grow_rule = re.search(
        r"\.form-actions\s*>\s*button:not\(\.form-actions-destructive\)[^{]*\{[^}]*flex:\s*1",
        css,
        re.DOTALL,
    )
    assert grow_rule is not None, (
        ".form-actions > button:not(.form-actions-destructive) must declare "
        "`flex: 1 ...` so Save/Cancel fill the row's width — without it the "
        "cluster falls short of the form's right edge"
    )
    role_button_rule = re.search(
        r"\.form-actions\s*>\s*\[role=\"button\"\]:not\(\.form-actions-destructive\)[^{]*\{[^}]*flex:\s*1",
        css,
        re.DOTALL,
    )
    assert role_button_rule is not None, (
        '`[role="button"]` (Cancel link styled as button) must follow the '
        "same flex-grow rule as `<button>` — without it the Cancel half of "
        "the row stays content-width"
    )
    # And the destructive button must NOT grow — Delete keeps its
    # content width on the right edge.
    destructive_rule = re.search(
        r"\.form-actions\s*>\s*\.form-actions-destructive\b[^{]*\{[^}]*margin-left:\s*auto",
        css,
        re.DOTALL,
    )
    assert destructive_rule is not None, (
        ".form-actions-destructive must declare `margin-left: auto` so "
        "Delete stays right-aligned and content-sized"
    )


def test_actions_macro_routes_page_level_clusters_through_form_wrapper() -> None:
    """Every form-layout cluster routes through the `actions` macro so the
    `.form-actions` styling is consistent. Pinned because the bare
    `<div class="form-actions">` that used to live in `clinicians/form_edit.html`
    diverged from the macro's styling on the desktop width fix.

    With the component-library default in place (`wrapper="form"` +
    omitted `submit_label` → "Save changes"), the canonical edit cluster
    is `actions(cancel_url=...)` — both buttons render and styling stays
    uniform. The Cancel-only carve-out the macro used to support was
    dropped when the README's "every edit form uses Save changes"
    rule moved into the macro itself (see
    `test_form_layout_submit_label_defaults_to_save_changes` in
    `_shared/test_actions.py`)."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% from "_shared/actions.html" import actions %}
        <div id="cluster">
          {{ actions(cancel_url="/widgets/1") }}
        </div>
        """,
    )
    html = env.get_template("stub.html").render()
    tree = HTMLParser(html)
    cluster = tree.css_first("#cluster .form-actions")
    assert cluster is not None, "macro must render `.form-actions` wrapper"
    # The default "Save changes" submit button renders.
    submit = cluster.css_first("button[type='submit']")
    assert submit is not None
    assert submit.text().strip() == "Save changes"
    # Cancel link is present and points at the supplied URL.
    cancel = cluster.css_first("a[role='button']")
    assert cancel is not None
    assert cancel.attributes.get("href") == "/widgets/1"


def test_no_template_uses_danger_class() -> None:
    """The custom `.danger` button class was removed when its Pico-token
    overrides weren't taking effect. Guard against re-introducing
    `class="danger"` anywhere in the template tree — if a destructive
    color treatment is added back later, it should land via a new
    selector + CSS in one place, not via per-template class strings."""
    import re
    from pathlib import Path

    templates_roots = [
        Path("src/framework/templates"),
        Path("src/domain/templates"),
    ]
    violations: list[str] = []
    for root in templates_roots:
        for path in root.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r'class="([^"]*)"', text):
                classes = match.group(1).split()
                if "danger" in classes:
                    violations.append(f"{path}: {match.group(0)}")

    assert not violations, (
        "the `.danger` class was removed; do not reintroduce it on "
        "template markup. Found:\n  " + "\n  ".join(violations)
    )


def test_list_page_heading_visible_on_mobile() -> None:
    """Regression for #588 — the list-page heading (`Organizations`,
    `Posts`, `Clinicians`, `Users`) must stay visible at the 375px
    mobile viewport.

    Earlier the heading lived in a single-segment breadcrumb above
    the toolbar, and a `@media (max-width: 768px)` rule unconditionally
    hid `nav[aria-label="breadcrumb"]` — dropping the page-heading
    context on mobile list pages.

    The breadcrumb-toolbar consolidation moved the heading into the
    toolbar `<h1>` (and removed the breadcrumb from list pages
    entirely), so the heading is now part of the same row as Filters /
    Create. This test pins the new arrangement: the `<h1>` is rendered
    inside the toolbar and carries no mobile-hide rule.
    """
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    tree = HTMLParser(html)
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None, "list-page heading must live in the toolbar <h1>"
    assert h1.text(strip=True) == "Clinicians"

    # The CSS must not blanket-hide the toolbar or its `<h1>` on
    # narrow viewports — the page heading has to stay visible.
    assert not re.search(
        r"@media[^{]*max-width[^{]*\{[^}]*\.toolbar[^}]*display:\s*none",
        html,
    ), "toolbar must not be hidden on mobile — the page heading lives there"
    assert not re.search(
        r"@media[^{]*max-width[^{]*\{[^}]*\.toolbar\s+h1[^}]*display:\s*none",
        html,
    ), "toolbar h1 must not be hidden on mobile — that's the page heading"


def test_entity_form_page_caps_short_field_widths() -> None:
    """Regression for #585 — every input inside `.entity-form-page`
    that holds a short, bounded value (5-digit ZIP, 2-letter state,
    10-digit NPI, ISO date, short numeric ID) must carry a `max-width`
    cap so it doesn't stretch to the full form-container width on
    desktop. The cap is applied via `name`-attribute selectors in
    `domain.css` so per-template wiring isn't required — adding a field
    with one of the capped names anywhere inside an `.entity-form-page`
    picks up the right width automatically."""
    import re
    from pathlib import Path

    css = (
        Path(__file__).parent.parent.parent / "domain" / "static" / "css" / "domain.css"
    ).read_text()

    # The ZIP / state-code group caps at the narrow tier.
    narrow = re.search(
        r"\.entity-form-page\s+input\[name=\"location_zip\"\][^{]*\{[^}]*max-width:\s*8rem",
        css,
        re.DOTALL,
    )
    assert narrow is not None, (
        "domain.css must cap `location_zip` width inside `.entity-form-page` "
        "so a 5-digit ZIP doesn't stretch the form container (#585)"
    )

    # NPI + ISO-date group caps at the medium tier.
    medium = re.search(
        r"\.entity-form-page\s+input\[name=\"npi\"\][^{]*\{[^}]*max-width:\s*12rem",
        css,
        re.DOTALL,
    )
    assert medium is not None, (
        "domain.css must cap `npi` width inside `.entity-form-page` so a "
        "10-digit NPI doesn't stretch the form container (#585)"
    )

    # State <select> shares the narrow cap.
    state = re.search(
        r"\.entity-form-page\s+select\[name=\"location_state\"\][^{]*\{[^}]*max-width:\s*8rem",
        css,
        re.DOTALL,
    )
    assert state is not None, (
        'domain.css must cap `<select name="location_state">` width inside '
        "`.entity-form-page` (#585)"
    )

    # Generic date-input cap so any `<input type=\"date\">` (e.g. the
    # program start/end-date fields) picks up the cap without naming.
    date_input = re.search(
        r"\.entity-form-page\s+input\[type=\"date\"\][^{]*\{[^}]*max-width:\s*12rem",
        css,
        re.DOTALL,
    )
    assert date_input is not None, (
        'domain.css must cap `<input type="date">` width inside '
        "`.entity-form-page` so program start/end dates don't stretch (#585)"
    )


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


def _request_stub(path: str = "/", query: dict[str, str] | None = None) -> _RequestStub:
    stub = _RequestStub()
    stub.url = _RequestStub._Url()
    stub.url.path = path
    stub.query_params = query or {}
    return stub


def _render_chrome(path: str, query: dict[str, str] | None = None) -> str:
    """Render the primary-nav chrome from `base.html` (via any view-type
    template) at a given URL + query string. Authenticated path — the
    section shortcuts are gated on `is_authenticated`."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Stub{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    return env.get_template("stub.html").render(
        request=_request_stub(path=path, query=query),
        is_authenticated=True,
        is_development=False,
    )


def _active_tab_labels(html: str) -> list[str]:
    """Extract the link text of every primary-nav anchor carrying
    `aria-current="page"`. Returns labels (e.g. ``["Directory"]``) so
    assertions read naturally."""
    tree = HTMLParser(html)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None, "primary nav missing"
    return [a.text(strip=True) for a in nav.css("a[aria-current='page']")]


def _render_base_for_path(path: str) -> str:
    """Render ``base.html`` for an anonymous visitor at the given path.

    The base template only differs from a child render in that nothing
    fills `{% block content %}`; we still get the full nav scaffold.
    """
    env = _make_env()
    return env.get_template("base.html").render(
        request=_request_stub(path),
        is_authenticated=False,
        is_development=False,
    )


def test_login_link_color_is_consistent_across_auth_pages() -> None:
    """Regression for #592 — the top-right Login link must not carry
    `class="contrast"` on `/auth/login` (which previously rendered the
    link black) while the same link on `/auth/register` and
    `/auth/forgot-password` rendered blue. Drop the contrast class so
    the link's color stays the same color anywhere it's still rendered.

    After #591 lands, the Login link is replaced by a `<span>` on
    auth-flow paths so there's no `<a href="/auth/login">` to check on
    those paths — the assertion-on-the-empty-set still holds, and the
    test stays useful as a guard against re-introducing a colored link
    if the suppression rule is ever loosened."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Login{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )
    for path in ("/auth/login", "/auth/register", "/auth/forgot-password"):
        html = env.get_template("stub.html").render(
            request=_request_stub(path=path),
            is_authenticated=False,
            is_development=False,
        )
        tree = HTMLParser(html)
        login_links = [
            a for a in tree.css('a[href="/auth/login"]') if a.text().strip() == "Login"
        ]
        for link in login_links:
            classes = (link.attributes.get("class") or "").split()
            assert (
                "contrast" not in classes
            ), f"on {path}, Login link must not use `class='contrast'`: got {classes!r}"


# --- Primary nav: section active-state + Login shortcut --------------


def test_primary_nav_posts_active_on_posts_list() -> None:
    """`/posts` is the canonical Posts URL — the avatar menu's "My posts"
    entry (the only Posts-family link) is active there."""
    assert _active_tab_labels(_render_chrome("/posts")) == ["My posts"]


def test_primary_nav_posts_active_on_posts_subpath() -> None:
    """Subpaths under `/posts` (detail, edit, form) keep the "My posts"
    avatar-menu entry lit — same path-prefix rule Directory uses."""
    assert _active_tab_labels(_render_chrome("/posts/42")) == ["My posts"]
    assert _active_tab_labels(_render_chrome("/posts/42/form")) == ["My posts"]
    assert _active_tab_labels(_render_chrome("/posts/form")) == ["My posts"]


def test_primary_nav_no_tab_active_on_non_journey_paths() -> None:
    """Neither Referrals nor Openings is active on URL families that
    aren't chrome-promoted (`/clinicians`, `/intakes`, `/organizations`,
    `/programs`, `/users`). The journey-1 bias intentionally leaves the
    primary nav inert on these still-reachable-by-URL surfaces."""
    for path in ("/clinicians", "/intakes", "/organizations", "/users"):
        labels = _active_tab_labels(_render_chrome(path))
        assert labels == [], f"{path} should not light any nav tab, got {labels}"


def test_primary_nav_omits_login_link_for_anonymous_visitors() -> None:
    """Anonymous visitors see only the brand in the chrome — no Login
    shortcut, no self-referential indicator. Visitors enter the auth
    flow from the landing page CTA. Pin the no-link contract across
    every anonymous-accessible URL family so a regression doesn't
    silently re-introduce the link."""
    for path in (
        "/",
        "/auth/login",
        "/auth/register",
        "/auth/forgot-password",
        "/auth/reset-password/some-token",
    ):
        html = _render_base_for_path(path)
        tree = HTMLParser(html)
        assert (
            tree.css_first('nav[aria-label="Primary"] a[href="/auth/login"]') is None
        ), f"expected no /auth/login link on {path}"
        assert (
            tree.css_first('nav[aria-label="Primary"] span[aria-current="page"]')
            is None
        ), f"expected no Login indicator on {path}"


def test_list_view_resource_label_auto_fills_from_context() -> None:
    """``handle_list`` injects ``resource_label`` from the spec; child
    templates that don't override ``{% block resource_label %}`` get the
    injected value automatically — no per-template block needed."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        resource_label="Clinicians",
    )

    toolbar_h1 = HTMLParser(html).css_first("div.toolbar h1")
    assert toolbar_h1 is not None
    assert toolbar_h1.text(strip=True) == "Clinicians"


def test_list_view_block_override_takes_precedence_over_context_label() -> None:
    """An explicit ``{% block resource_label %}`` override wins over the
    context-injected value — used by pages whose display name differs from
    the spec's ``url_collection`` (e.g. posts overriding toolbar entirely)."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}My Custom Label{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        resource_label="Would Be Overridden",
    )

    toolbar_h1 = HTMLParser(html).css_first("div.toolbar h1")
    assert toolbar_h1 is not None
    assert toolbar_h1.text(strip=True) == "My Custom Label"
