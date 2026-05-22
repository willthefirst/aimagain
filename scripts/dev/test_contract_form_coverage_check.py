"""Tests for `scripts/dev/contract_form_coverage_check.py`.

The lint's job is to flag a form whose submit URL has no matching
`ContractPair.endpoints` entry and is not in `FORMS_WITHOUT_PAIRS`.
The forgot-password bug that motivated this check would have been
caught by this lint if it had existed; one of the tests below
constructs that exact scenario and asserts the lint reports it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.dev import contract_form_coverage_check as lint
from scripts.dev.contract_form_coverage_check import (
    _is_dynamic_url,
    _scan_file,
    _static_prefix,
)


def _write(tmp_path: Path, body: str, name: str = "page.html") -> Path:
    file = tmp_path / name
    file.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return file


# --- URL parsing --------------------------------------------------------------


def test_static_prefix_strips_jinja_block():
    """A URL like `/auth/jwt/login{% if next %}?...{% endif %}` has
    static prefix `/auth/jwt/login` — that's what providers route on."""
    assert _static_prefix("/foo{% if x %}?a={{ b }}{% endif %}") == "/foo"
    assert _static_prefix("/static/path") == "/static/path"
    assert _static_prefix("{{ entity_url('x') }}") == ""


def test_is_dynamic_url_recognises_template_only_urls():
    """Pure-Jinja URLs (`{{ entity_url(...) }}`) are dynamic — the
    lint can't resolve them statically so it skips them."""
    assert _is_dynamic_url("{{ entity_url('clinician') }}") is True
    # Has static prefix → in scope.
    assert _is_dynamic_url("/auth/login{% if x %}?n={{ x }}{% endif %}") is False
    # Plain literal → in scope.
    assert _is_dynamic_url("/auth/forgot-password") is False
    # String concatenation → dynamic.
    assert _is_dynamic_url('"/clinicians/" ~ provider.id ~ "/licensures"') is True


# --- Form extraction ----------------------------------------------------------


def test_scan_extracts_htmx_post_url(tmp_path):
    file = _write(
        tmp_path,
        """
        <form hx-post="/auth/forgot-password" hx-ext="json-enc">
          <input name="email" />
        </form>
        """,
    )
    subs = list(_scan_file(file))
    assert len(subs) == 1
    assert subs[0].key == "POST /auth/forgot-password"


def test_scan_extracts_bare_html_form_method_action(tmp_path):
    """Pre-htmx `<form method="post" action="/x">` is still in scope —
    this shape is the original forgot-password bug. The lint must
    catch it."""
    file = _write(
        tmp_path,
        """
        <form method="post" action="/auth/forgot-password">
          <input name="email" />
        </form>
        """,
    )
    subs = list(_scan_file(file))
    assert len(subs) == 1
    assert subs[0].key == "POST /auth/forgot-password"


def test_scan_skips_dynamic_macro_form(tmp_path):
    """Entity-form macros use `hx-{{ method }}="{{ action }}"`. These
    flow through the entity dispatch layer; coverage is handled by the
    per-entity contract pairs already in the manifest. The lint stays
    silent on them rather than producing false positives."""
    file = _write(
        tmp_path,
        """
        {% macro entity_form(method, action) %}
        <form hx-{{ method }}="{{ action }}">
        </form>
        {% endmacro %}
        """,
    )
    assert list(_scan_file(file)) == []


def test_scan_recovers_static_prefix_from_jinja_block_in_action(tmp_path):
    """The login form embeds a Jinja conditional inside the `action`
    attribute. The static prefix `/auth/jwt/login` is still what the
    provider routes on — pin that it gets extracted."""
    file = _write(
        tmp_path,
        """
        <form
            method="post"
            action="/auth/jwt/login{% if next %}?next={{ next }}{% endif %}">
        </form>
        """,
    )
    subs = list(_scan_file(file))
    assert len(subs) == 1
    assert subs[0].key == "POST /auth/jwt/login"


def test_scan_handles_multiple_forms_in_one_file(tmp_path):
    file = _write(
        tmp_path,
        """
        <form hx-post="/auth/a"></form>
        <form hx-delete="/auth/b"></form>
        <form hx-patch="/auth/c"></form>
        """,
    )
    keys = {s.key for s in _scan_file(file)}
    assert keys == {"POST /auth/a", "DELETE /auth/b", "PATCH /auth/c"}


def test_scan_ignores_get_forms(tmp_path):
    """Search forms use `method=get` (or no method, defaulting to GET).
    GETs have no body to encode; nothing for the contract layer to
    pin. Out of scope."""
    file = _write(
        tmp_path,
        """
        <form action="/search" method="get">
          <input name="q" />
        </form>
        """,
    )
    assert list(_scan_file(file)) == []


# --- End-to-end main behavior ------------------------------------------------


def test_main_passes_when_every_submission_is_paired(monkeypatch, capsys, tmp_path):
    """End-to-end happy path: render a form whose URL is in the
    pair list; main() exits 0."""
    page = _write(
        tmp_path,
        '<form hx-post="/auth/special-route"></form>',
    )
    monkeypatch.setattr(lint, "_TEMPLATE_ROOTS", (tmp_path,))
    monkeypatch.setattr(
        lint,
        "_load_manifest_endpoints",
        lambda: {"POST /auth/special-route"},
    )
    monkeypatch.setattr(lint, "FORMS_WITHOUT_PAIRS", {})

    assert lint.main() == 0
    out = capsys.readouterr().out
    assert "all covered" in out


def test_main_passes_via_forms_without_pairs_allowlist(monkeypatch, capsys, tmp_path):
    """The allowlist is the second escape hatch — entries here are
    intentionally not paired with a justification. End-to-end: a form
    whose URL is in the allowlist should pass."""
    _write(
        tmp_path,
        '<form hx-post="/auth/sign-out"></form>',
    )
    monkeypatch.setattr(lint, "_TEMPLATE_ROOTS", (tmp_path,))
    monkeypatch.setattr(lint, "_load_manifest_endpoints", lambda: set())
    monkeypatch.setattr(
        lint,
        "FORMS_WITHOUT_PAIRS",
        {"POST /auth/sign-out": "empty body; nothing to pin"},
    )

    assert lint.main() == 0


def test_main_fails_when_submission_has_no_pair_or_allowlist_entry(
    monkeypatch, capsys, tmp_path
):
    """The regression case the lint exists to catch: a literal-URL
    form whose endpoint is not in any pair and not in the allowlist.
    This is exactly the shape the original forgot-password bug had
    on main before PR #770. The lint must report it and exit 1."""
    _write(
        tmp_path,
        '<form hx-post="/auth/forgot-password" hx-ext="json-enc"></form>',
    )
    monkeypatch.setattr(lint, "_TEMPLATE_ROOTS", (tmp_path,))
    monkeypatch.setattr(lint, "_load_manifest_endpoints", lambda: set())
    monkeypatch.setattr(lint, "FORMS_WITHOUT_PAIRS", {})

    rc = lint.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "POST /auth/forgot-password" in out
    # Failure message should point at the two ways to resolve.
    assert "ContractPair" in out
    assert "FORMS_WITHOUT_PAIRS" in out


# --- Manifest integration -----------------------------------------------------


def test_real_manifest_covers_every_real_form():
    """Smoke test against the live manifest + live templates: there
    should be zero violations on main. If this test starts failing,
    a real form has been added without a matching pair — the
    structural prevention the lint is designed to give."""
    submissions = lint._gather_submissions()
    paired = lint._load_manifest_endpoints()
    allowlist = set(lint.FORMS_WITHOUT_PAIRS)
    uncovered = [
        s for s in submissions if s.key not in paired and s.key not in allowlist
    ]
    assert uncovered == [], (
        "Uncovered form submissions found — add to a ContractPair's "
        "endpoints or to FORMS_WITHOUT_PAIRS: " + ", ".join(s.key for s in uncovered)
    )
