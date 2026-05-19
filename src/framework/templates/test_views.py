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


def test_primary_nav_shows_admin_links_only_for_admins() -> None:
    """Regression for #590 — `/organizations`, `/programs`, `/users` are
    admin tools, not surfaces for ordinary viewers. Render the chrome
    twice: once as an admin (the three links appear), once as a
    non-admin authenticated user (the links don't render).
    Referrals/Openings/Directory render for any authed user."""
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

    admin_html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_admin=True,
        is_development=False,
    )
    nonadmin_html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=True,
        is_admin=False,
        is_development=False,
    )

    admin_tree = HTMLParser(admin_html)
    admin_links = {
        a.attributes.get("href") for a in admin_tree.css('nav[aria-label="Primary"] a')
    }
    assert "/organizations" in admin_links, "admin nav must include Organizations link"
    assert "/programs" in admin_links, "admin nav must include Programs link"
    assert "/users" in admin_links, "admin nav must include Users link"

    nonadmin_tree = HTMLParser(nonadmin_html)
    nonadmin_links = {
        a.attributes.get("href")
        for a in nonadmin_tree.css('nav[aria-label="Primary"] a')
    }
    assert (
        "/organizations" not in nonadmin_links
    ), "non-admin viewer must not see Organizations link"
    assert (
        "/programs" not in nonadmin_links
    ), "non-admin viewer must not see Programs link"
    assert "/users" not in nonadmin_links, "non-admin viewer must not see Users link"
    # Referrals/Openings/Directory still present for the authed non-admin.
    assert "/providers" in nonadmin_links


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


def test_breadcrumb_page_heading_visible_on_mobile() -> None:
    """Regression for #588 — the single-segment breadcrumb on every
    list page (`Organizations`, `Posts`, `Providers`, `Users`) doubles
    as the page heading and must stay visible at the 375px mobile
    viewport. Earlier the mobile rule hid `nav[aria-label="breadcrumb"]`
    unconditionally under `@media (max-width: 768px)`, dropping the
    page-heading context on mobile list pages and leaving only the
    Filters/Create row as the top of the page.

    The fix scopes the hide to multi-segment breadcrumbs only via the
    `:has(li + li)` selector — single-segment list-page breadcrumbs
    stay visible; multi-segment detail/form breadcrumbs (location
    context) still collapse on mobile.
    """
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

    # Find every `@media (max-width: 768px)` block and verify none of
    # them blanket-hide `nav[aria-label="breadcrumb"]` — the rule must
    # be scoped to multi-segment via `:has(li + li)`.
    blocks_768 = re.findall(
        r"@media\s*\(\s*max-width:\s*768px\s*\)\s*\{(.*?)\n      \}",
        html,
        re.DOTALL,
    )
    assert blocks_768, "no @media (max-width: 768px) block in base.html"
    combined = "\n".join(blocks_768)
    assert (
        'nav[aria-label="breadcrumb"]:has(li + li)' in combined
    ), "mobile breadcrumb hide must be scoped to `:has(li + li)` so single-segment list-page breadcrumbs stay visible (#588)"
    # And the unscoped version must not appear — that would re-hide
    # the page heading on mobile list pages.
    assert not re.search(
        r"nav\[aria-label=\"breadcrumb\"\]\s*\{\s*display:\s*none",
        combined,
    ), 'unscoped `nav[aria-label="breadcrumb"] { display: none }` in a mobile @media block would hide the page heading on list pages (#588)'


def test_entity_form_page_caps_short_field_widths() -> None:
    """Regression for #585 — every input inside `.entity-form-page`
    that holds a short, bounded value (5-digit ZIP, 2-letter state,
    10-digit NPI, ISO date, short numeric ID) must carry a `max-width`
    cap so it doesn't stretch to the full form-container width on
    desktop. The cap is applied via `name`-attribute selectors in
    `base.html` so per-template wiring isn't required — adding a field
    with one of the capped names anywhere inside an `.entity-form-page`
    picks up the right width automatically."""
    import re

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

    # The ZIP / state-code group caps at the narrow tier.
    narrow = re.search(
        r"\.entity-form-page\s+input\[name=\"location_zip\"\][^{]*\{[^}]*max-width:\s*8rem",
        html,
        re.DOTALL,
    )
    assert narrow is not None, (
        "base.html must cap `location_zip` width inside `.entity-form-page` "
        "so a 5-digit ZIP doesn't stretch the form container (#585)"
    )

    # NPI + ISO-date group caps at the medium tier.
    medium = re.search(
        r"\.entity-form-page\s+input\[name=\"npi\"\][^{]*\{[^}]*max-width:\s*12rem",
        html,
        re.DOTALL,
    )
    assert medium is not None, (
        "base.html must cap `npi` width inside `.entity-form-page` so a "
        "10-digit NPI doesn't stretch the form container (#585)"
    )

    # State <select> shares the narrow cap.
    state = re.search(
        r"\.entity-form-page\s+select\[name=\"location_state\"\][^{]*\{[^}]*max-width:\s*8rem",
        html,
        re.DOTALL,
    )
    assert state is not None, (
        'base.html must cap `<select name="location_state">` width inside '
        "`.entity-form-page` (#585)"
    )

    # Generic date-input cap so any `<input type=\"date\">` (e.g. the
    # program start/end-date fields) picks up the cap without naming.
    date_input = re.search(
        r"\.entity-form-page\s+input\[type=\"date\"\][^{]*\{[^}]*max-width:\s*12rem",
        html,
        re.DOTALL,
    )
    assert date_input is not None, (
        'base.html must cap `<input type="date">` width inside '
        "`.entity-form-page` so program start/end dates don't stretch (#585)"
    )


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


def test_primary_nav_directory_active_on_providers_list() -> None:
    """`/providers` is the canonical Directory URL — its tab is active."""
    assert _active_tab_labels(_render_chrome("/providers")) == ["Directory"]


def test_primary_nav_directory_active_on_provider_detail() -> None:
    """Subpaths under `/providers` (detail, edit) keep Directory lit so
    the chrome stays consistent through the full provider drill-down."""
    assert _active_tab_labels(_render_chrome("/providers/42")) == ["Directory"]
    assert _active_tab_labels(_render_chrome("/providers/42/form")) == ["Directory"]


def test_primary_nav_referrals_active_on_posts_kind_referral() -> None:
    """`/posts?kind=referral` is the canonical Referrals URL."""
    assert _active_tab_labels(_render_chrome("/posts", query={"kind": "referral"})) == [
        "Referrals"
    ]


def test_primary_nav_openings_active_on_posts_kind_opening() -> None:
    """`/posts?kind=opening` is the canonical Openings URL."""
    assert _active_tab_labels(_render_chrome("/posts", query={"kind": "opening"})) == [
        "Openings"
    ]


def test_primary_nav_no_section_tab_on_bare_posts_list() -> None:
    """Bare `/posts` (no `?kind=`) is ambiguous between Referrals and
    Openings — neither tab claims it. The toolbar/list-page content
    carries the context instead."""
    assert _active_tab_labels(_render_chrome("/posts")) == []


def test_primary_nav_no_section_tab_on_post_detail() -> None:
    """Post detail URLs (`/posts/<id>`) drop the `?kind=` query param,
    so the section tabs intentionally don't light up — the post's own
    breadcrumb carries the context instead. Keeps the rule simple:
    only the canonical filtered list lights a section tab."""
    assert _active_tab_labels(_render_chrome("/posts/42")) == []


def test_primary_nav_active_link_carries_strong_style_hook() -> None:
    """The active link adds `class="contrast"` so the Pico color cue
    fires alongside the CSS rule that thickens the underline. Pinning
    both attributes ensures a future refactor that drops one notices
    the other."""
    html = _render_chrome("/providers")
    tree = HTMLParser(html)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    active = nav.css_first("a[aria-current='page']")
    assert active is not None
    assert "contrast" in (active.attributes.get("class") or "")


def test_primary_nav_renders_login_link_off_auth_flow() -> None:
    """When an anonymous visitor is *not* on an auth-flow page, the
    top-right Login shortcut renders as a clickable `<a
    href="/auth/login">` — the default chrome state."""
    html = _render_base_for_path("/")
    tree = HTMLParser(html)
    link = tree.css_first('#primary-nav a[href="/auth/login"]')
    assert link is not None
    # No `<span aria-current="page">` on a non-auth path.
    assert tree.css_first('#primary-nav span[aria-current="page"]') is None
    # When rendered as a link, no `class="contrast"` — keeps color
    # consistent with how the link would render anywhere else in the
    # chrome (#592). The auth-flow `<span>` variant carries `contrast`
    # because it's a non-link indicator, not a navigation target.
    classes = (link.attributes.get("class") or "").split()
    assert (
        "contrast" not in classes
    ), f"Login link must not use `class='contrast'`: got {classes!r}"


def test_primary_nav_suppresses_login_link_on_auth_flow_paths() -> None:
    """Issue #591: on `/auth/login`, `/auth/register`,
    `/auth/forgot-password`, and any `/auth/reset-password/...` path,
    the top-right Login shortcut renders as a non-link
    `<span aria-current="page">Login</span>` so the chrome doesn't
    offer a self-referential click target."""
    for path in (
        "/auth/login",
        "/auth/register",
        "/auth/forgot-password",
        "/auth/reset-password/some-token",
    ):
        html = _render_base_for_path(path)
        tree = HTMLParser(html)
        assert (
            tree.css_first('#primary-nav a[href="/auth/login"]') is None
        ), f"expected no /auth/login link on {path}"
        indicator = tree.css_first('#primary-nav span[aria-current="page"]')
        assert indicator is not None, f"expected Login indicator on {path}"
        assert indicator.text().strip() == "Login"
