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
    ``clinicians/list.html`` from the domain root.
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


def test_list_view_renders_h1_in_toolbar_and_omits_breadcrumb() -> None:
    """``views/list.html`` puts the `resource_label` into the
    toolbar `<h1>` (the page title) and renders no breadcrumb —
    a single-segment "Clinicians" trail would duplicate what the
    active global-nav tab already communicates, so list pages
    skip the breadcrumb entirely. The child only declares the
    label."""
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
        is_authenticated=False,
        is_development=False,
    )

    tree = HTMLParser(html)
    # No breadcrumb on list pages.
    assert tree.css_first('nav[aria-label="breadcrumb"]') is None
    # The heading lives in the toolbar `<h1>`.
    toolbar_h1 = tree.css_first("div.toolbar h1")
    assert toolbar_h1 is not None
    assert toolbar_h1.text(strip=True) == "Clinicians"
    # Content block lands in the page body.
    assert '<div id="body">ok</div>' in html


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


def test_detail_view_renders_back_affordance_and_actions() -> None:
    """``views/detail.html`` builds `[(resource_label, resource_url)]`
    and the breadcrumb macro renders it as a single back affordance —
    `<a class="breadcrumb-back" href="/clinicians">…Clinicians</a>`.
    Actions land inside the shared two-zone toolbar — empty left zone
    (no search link), and a `<menu class="toolbar-right">` carrying
    the `<li>` commands. Pins the "detail actions land at the same
    right edge as list-page actions" rule (no per-view-type toolbar
    shape)."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/detail.html" %}
        {% set resource_url = "/clinicians" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block actions %}<li><a id="edit" href="/clinicians/1/form">Edit</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    tree = HTMLParser(html)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None and back.attributes.get("href") == "/clinicians"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == "Clinicians"
    assert "Sunrise Therapy" in html
    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    # No search link on detail pages — left zone stays empty.
    assert 'class="toolbar-filter-link"' not in html
    assert '<li><a id="edit" href="/clinicians/1/form">Edit</a></li>' in html


def test_form_new_view_renders_create_heading_from_context() -> None:
    """``views/form_new.html`` reads ``create_heading`` from the
    handler-supplied context and renders it as the toolbar `<h1>`.
    The handler computes it via `create_label_for(spec, kind=...)`,
    the same helper every "Create X" CTA reads from, so the page
    title can't drift from the button that opened it."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_new.html" %}
        {% set resource_url = "/clinicians" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        create_heading="Create clinician",
    )

    tree = HTMLParser(html)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None and back.attributes.get("href") == "/clinicians"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == "Clinicians"
    assert "<h1>Create clinician</h1>" in html
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
        # Posts tab is present.
        assert "/posts" in nav_links
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
    """``views/form_edit.html`` renders a single-link back affordance
    pointing at the row's detail page (the deepest clickable parent of
    an edit view) above an `<h1>"Edit <noun>"` sourced from
    `edit_heading`. The back link's label is the row's identity
    (`current_label`) — "back to Sunrise Therapy" is the natural verb.
    The H1 reads the resource noun ("clinician", "clinician opening",
    "client referral") rather than the row's identity, mirroring the
    create-page contract where `create_heading` sources the H1."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_edit.html" %}
        {% set resource_url = "/clinicians" %}
        {% set resource_detail_url = "/clinicians/42" %}
        {% block resource_label %}Clinicians{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        edit_heading="Edit clinician",
    )

    tree = HTMLParser(html)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None, "form-edit must render a back affordance"
    assert (
        back.attributes.get("href") == "/clinicians/42"
    ), "back link points at the deepest clickable parent (the row's detail page)"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == "Sunrise Therapy"
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
    Pinned against `base.html` so a future CSS edit that drops the
    grow rule fails here loudly."""
    import re

    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_new.html" %}
        {% set resource_url = "/widgets" %}
        {% block resource_label %}Widgets{% endblock %}
        {% block content %}<form></form>{% endblock %}
        """,
    )
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )
    # The non-destructive Save/Cancel rule must `flex: 1` (any
    # `1 1 0` / `1` variant) so they grow. Match the property
    # against any value that starts with `1`.
    grow_rule = re.search(
        r"\.form-actions\s*>\s*button:not\(\.form-actions-destructive\)[^{]*\{[^}]*flex:\s*1",
        html,
        re.DOTALL,
    )
    assert grow_rule is not None, (
        ".form-actions > button:not(.form-actions-destructive) must declare "
        "`flex: 1 ...` so Save/Cancel fill the row's width — without it the "
        "cluster falls short of the form's right edge"
    )
    role_button_rule = re.search(
        r"\.form-actions\s*>\s*\[role=\"button\"\]:not\(\.form-actions-destructive\)[^{]*\{[^}]*flex:\s*1",
        html,
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
        html,
        re.DOTALL,
    )
    assert destructive_rule is not None, (
        ".form-actions-destructive must declare `margin-left: auto` so "
        "Delete stays right-aligned and content-sized"
    )


def test_actions_macro_supports_cancel_only_for_page_level_clusters() -> None:
    """The `actions` macro accepts `submit_label=None` so multi-section
    pages (e.g. `clinicians/form_edit.html`) can render a page-level
    Cancel-only cluster without a redundant Save button. Pinned because
    the bare `<div class="form-actions">` that used to live in that
    template diverged from the macro's styling on the desktop width fix
    — every cluster must route through the macro."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% from "_shared/actions.html" import actions %}
        <div id="cancel-only">
          {{ actions(cancel_url="/widgets/1") }}
        </div>
        """,
    )
    html = env.get_template("stub.html").render()
    tree = HTMLParser(html)
    cluster = tree.css_first("#cancel-only .form-actions")
    assert cluster is not None, "macro must still render `.form-actions` wrapper"
    # No submit button when `submit_label` is omitted.
    assert (
        cluster.css_first("button[type='submit']") is None
    ), "Cancel-only cluster must not render a stray Save button"
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
        {% set resource_url = "/clinicians" %}
        {% block resource_label %}Clinicians{% endblock %}
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
    """`/posts` is the canonical Posts URL — its tab is active."""
    assert _active_tab_labels(_render_chrome("/posts")) == ["Posts"]


def test_primary_nav_posts_active_on_posts_subpath() -> None:
    """Subpaths under `/posts` (detail, edit, form) keep the Posts tab
    lit — same path-prefix rule Directory uses."""
    assert _active_tab_labels(_render_chrome("/posts/42")) == ["Posts"]
    assert _active_tab_labels(_render_chrome("/posts/42/form")) == ["Posts"]
    assert _active_tab_labels(_render_chrome("/posts/form")) == ["Posts"]


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
            tree.css_first('#primary-nav a[href="/auth/login"]') is None
        ), f"expected no /auth/login link on {path}"
        assert (
            tree.css_first('#primary-nav span[aria-current="page"]') is None
        ), f"expected no Login indicator on {path}"
