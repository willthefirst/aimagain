"""Tests for ``template_route_check``.

The lint reads its known-collection set from the live entity registry,
so adding a new top-level entity automatically extends the lint with no
script change. Tests below construct synthetic template content rather
than asserting against the repo's own templates (which a passing
``main()`` already pins indirectly).
"""

from scripts.dev.template_route_check import (
    _build_pattern,
    _strip_comments,
    _violations,
)

_COLLECTIONS = {"organizations", "clinicians", "posts", "users"}
_PATTERN = _build_pattern(_COLLECTIONS)


def _scan(text: str) -> list[str]:
    """Return the literal matches the pattern finds in ``text``,
    after stripping Jinja comments — mirrors ``_violations`` minus
    the file-system step."""
    stripped = _strip_comments(text)
    return [m.group(2) for m in _PATTERN.finditer(stripped)]


# --- The bug class -----------------------------------------------------


def test_flags_hardcoded_form_url_in_href():
    assert _scan('<a href="/organizations/form">New</a>') == ["/organizations/form"]


def test_flags_hardcoded_url_in_hx_post():
    assert _scan('<form hx-post="/posts">') == ["/posts"]


def test_flags_hardcoded_subresource_url():
    """Sub-of-known-collection paths (`/users/me`) start with a known
    top-level segment — still flagged. Author uses
    ``entity_url('user', id='me')`` or ``entity_url('user_favorite')``."""
    assert _scan('<a href="/users/me">Profile</a>') == ["/users/me"]


def test_flags_url_with_jinja_interpolation_in_middle():
    """Literal first segment is enough — interpolation doesn't rescue."""
    assert _scan('<a href="/posts/{{ post.id }}">x</a>') == ["/posts/{{ post.id }}"]


def test_flags_literal_in_set_statement():
    """Jinja statement blocks are NOT stripped — literals in
    ``{% set ... %}`` get caught too."""
    matches = _scan('{% set resource_url = "/organizations" %}')
    assert matches == ["/organizations"]


def test_flags_literal_in_macro_arg():
    """Macro calls inside ``{{ ... }}`` are not stripped — author
    should pass ``entity_url(...)`` to the macro instead."""
    matches = _scan('{{ confirm_delete_button("/posts/" ~ post.id, "Delete?") }}')
    assert "/posts/" in matches


def test_flags_literal_in_request_path_comparison():
    """The base.html nav uses ``request.url.path == '/users/me'`` to
    derive active-page state. Migration: hoist the path into a
    ``{% set _x = entity_url(...) %}`` and compare against ``_x``."""
    matches = _scan("{% if request.url.path == '/users/me' %}...{% endif %}")
    assert matches == ["/users/me"]


# --- The good cases ----------------------------------------------------


def test_does_not_flag_entity_url_call():
    """The whole point — the helper's output is the canonical URL
    and contains no literal collection path in template source."""
    assert _scan("<a href=\"{{ entity_url('post') }}\">Posts</a>") == []


def test_does_not_flag_entity_form_url_with_id():
    assert (
        _scan("<a href=\"{{ entity_form_url('clinician', id=p.id) }}\">Edit</a>") == []
    )


def test_does_not_flag_relative_url():
    """Query-only links (``?kind=referral``) are fine as-is —
    they don't anchor at a collection root."""
    assert _scan('<a href="?kind=referral">x</a>') == []


def test_does_not_flag_root_link():
    """The root link ``/`` doesn't start with any known collection."""
    assert _scan('<a href="/">Home</a>') == []


def test_does_not_flag_non_entity_first_segment():
    """``/auth/login`` and ``/static/foo.css`` aren't entity paths."""
    assert _scan('<a href="/auth/login">Sign in</a>') == []
    assert _scan('<link href="/static/style.css" rel="stylesheet">') == []


def test_does_not_flag_word_boundary_lookalike():
    """``/users_audit_log`` isn't ``/users`` — the ``\\b`` boundary
    after the collection name guards against false positives on names
    that share a prefix."""
    assert _scan('<a href="/users_audit_log/x">x</a>') == []


def test_strips_jinja_comments():
    """Doc-only examples inside ``{# ... #}`` blocks are stripped
    before scanning — macro headers can illustrate usage with literal
    paths without tripping the lint."""
    text = (
        "{# Example:\n"
        '  {{ inline_add_form("/clinicians/" ~ p.id ~ "/licensures") }}\n'
        "#}\n"
        '<form action="/posts">x</form>'
    )
    matches = _scan(text)
    # Only the live `/posts`, not the `/clinicians/` inside the comment.
    assert matches == ["/posts"]


def test_strips_multiline_jinja_comments():
    text = "{# line 1\nline 2 with /posts literal\nline 3 #}\nreal /posts is here"
    stripped = _strip_comments(text)
    assert "line 2" not in stripped
    assert "real /posts is here" in stripped


# --- Pattern construction ----------------------------------------------


def test_pattern_includes_all_known_collections():
    """The pattern is regenerated from the registry; every known
    collection must be in the alternation."""
    for c in _COLLECTIONS:
        # Match a literal URL for each collection.
        assert _PATTERN.search(f'"/{c}"')


def test_pattern_anchors_on_string_quote():
    """The lint matches inside a quoted string only — paths in prose
    text (not quoted) don't match. Avoids hitting docstring URLs in
    non-Jinja-comment prose."""
    assert _PATTERN.search("See /posts for more") is None
    assert _PATTERN.search('See "/posts" for more') is not None


# --- File-level integration --------------------------------------------


def test_violations_reports_file_and_line(tmp_path):
    f = tmp_path / "bad.html"
    f.write_text("<p>fine</p>\n" '<a href="/posts/form">new</a>\n' "<p>also fine</p>\n")
    out = _violations(f, _PATTERN)
    assert out == [(f, 2, "/posts/form")]


def test_violations_returns_empty_for_clean_file(tmp_path):
    f = tmp_path / "ok.html"
    f.write_text("<a href=\"{{ entity_url('post') }}\">Posts</a>")
    assert _violations(f, _PATTERN) == []
