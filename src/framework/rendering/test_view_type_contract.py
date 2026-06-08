"""Tests for the view-type chrome contract enforcement.

The validator runs once per `APIResponse.html_response` call: it walks
the rendered template's `{% extends %}` chain to its view-type parent
and asserts every key listed in `VIEW_TYPE_REQUIREMENTS` is present in
the merged context. Forgetting a key surfaces here with a clear message
instead of as a Jinja `UndefinedError` deep in a chrome block.

The tests below pin three contracts:

1. The required-keys table matches what each view-type template
   actually reads (template-source-driven pin, not docstring-driven).
2. The view-type resolver walks `{% extends %}` to the right parent
   for every domain template, and returns `None` for templates outside
   the view-type system.
3. The asserter raises with all missing keys named — partial failure
   isn't useful.
"""

from __future__ import annotations

import pytest

from src.framework.rendering.view_type_contract import (
    VIEW_TYPE_REQUIREMENTS,
    ViewTypeContextError,
    assert_view_type_context,
    missing_required_keys,
    view_type_for,
)

# --- view_type_for -----------------------------------------------------


def test_view_type_for_detail_template():
    """A domain template that extends `views/detail.html` resolves to
    that exact parent — the validator can then look up the right
    required-keys row."""
    assert view_type_for("organizations/detail.html") == "views/detail.html"
    assert view_type_for("users/detail.html") == "views/detail.html"


def test_view_type_for_form_new_template():
    assert view_type_for("clinicians/form_new.html") == "views/form_new.html"
    assert view_type_for("organizations/form_new.html") == "views/form_new.html"


def test_view_type_for_form_edit_template():
    assert view_type_for("clinicians/form_edit.html") == "views/form_edit.html"
    assert view_type_for("users/email_form.html") == "views/form_edit.html"


def test_view_type_for_search_template():
    assert view_type_for("posts/search.html") == "views/search.html"


def test_view_type_for_list_template():
    assert view_type_for("posts/list.html") == "views/list.html"
    assert view_type_for("favorites/list.html") == "views/list.html"


def test_view_type_for_base_extending_template_returns_none():
    """Templates that extend `base.html` (auth flow, home, landing,
    dev/components) are outside the view-type contract — the
    validator must skip them."""
    assert view_type_for("auth/login.html") is None
    assert view_type_for("home.html") is None
    assert view_type_for("landing.html") is None


def test_view_type_for_unknown_template_returns_none():
    """Typos / missing templates return None — the downstream
    `TemplateResponse` call surfaces its own `TemplateNotFound`."""
    assert view_type_for("totally-not-a-template.html") is None


def test_view_type_for_view_type_itself_returns_none():
    """`views/detail.html` extends `base.html`, not another view-type
    — the resolver is for child-of-view-type templates, not the
    view-type templates themselves."""
    assert view_type_for("views/detail.html") is None


# --- missing_required_keys --------------------------------------------


def test_missing_required_keys_empty_when_all_present():
    """Detail view requires `entity_name`; the merged context supplies
    it, so nothing is missing."""
    ctx = {"entity_name": "user", "request": object()}
    assert missing_required_keys("users/detail.html", ctx) == []


def test_missing_required_keys_reports_absent_key():
    """The merged context lacks `entity_name` — the validator surfaces
    that single key in the missing list."""
    ctx = {"request": object()}
    assert missing_required_keys("users/detail.html", ctx) == ["entity_name"]


def test_missing_required_keys_reports_every_absent_key_sorted():
    """form_edit requires three keys. Omitting all three surfaces all
    three in sorted order — partial fix-and-rerender isn't useful."""
    ctx = {"request": object()}
    assert missing_required_keys("clinicians/form_edit.html", ctx) == [
        "edit_heading",
        "entity_name",
        "resource_detail_url",
    ]


def test_missing_required_keys_empty_for_non_view_type_template():
    """Templates outside the view-type system (auth pages, etc.) are
    always "complete" from this validator's perspective."""
    assert missing_required_keys("auth/login.html", {}) == []


def test_missing_required_keys_empty_for_list_view():
    """`views/list.html` declares no required keys — all chrome
    access is guarded by `is defined` / `| default`."""
    assert missing_required_keys("posts/list.html", {}) == []


# --- assert_view_type_context -----------------------------------------


def test_assert_passes_when_keys_present():
    """Passing all required keys returns None and does not raise."""
    ctx = {"entity_name": "user", "request": object()}
    assert assert_view_type_context("users/detail.html", ctx) is None


def test_assert_raises_with_missing_keys_named():
    """The error message names every missing key so the handler
    author sees exactly what to add — no Jinja stack trace required."""
    ctx = {"request": object()}
    with pytest.raises(ViewTypeContextError) as excinfo:
        assert_view_type_context("clinicians/form_edit.html", ctx)
    msg = str(excinfo.value)
    assert "entity_name" in msg
    assert "edit_heading" in msg
    assert "resource_detail_url" in msg
    assert "views/form_edit.html" in msg
    assert "clinicians/form_edit.html" in msg


def test_assert_error_includes_pointer_to_table():
    """The error names `view_type_contract.py` so the fixer knows
    where the table lives (and can add a key if a new view-type
    requirement was missed)."""
    with pytest.raises(ViewTypeContextError) as excinfo:
        assert_view_type_context("users/detail.html", {})
    assert "view_type_contract" in str(excinfo.value)


def test_assert_is_a_value_error_subclass():
    """`ViewTypeContextError` is a `ValueError` so generic
    `except ValueError` handlers don't lose this signal."""
    assert issubclass(ViewTypeContextError, ValueError)


# --- table integrity --------------------------------------------------


def test_every_view_type_template_has_a_requirements_entry():
    """The required-keys table must list every concrete view-type
    template that exists on disk. Adding a new view-type chrome
    template without a table entry would let a future template
    silently skip the check."""
    from pathlib import Path

    views_dir = Path(__file__).resolve().parents[1] / "templates" / "views"
    on_disk = {f"views/{p.name}" for p in views_dir.glob("*.html")}
    assert on_disk == set(VIEW_TYPE_REQUIREMENTS), (
        f"`VIEW_TYPE_REQUIREMENTS` is out of sync with "
        f"`src/framework/templates/views/`. "
        f"On disk: {on_disk}. In table: {set(VIEW_TYPE_REQUIREMENTS)}."
    )


def test_required_keys_match_template_source():
    """Every key listed for a view type must actually appear in that
    template's source. Pins the table against silent drift if a
    template is refactored to drop a key — the key should leave the
    table at the same time."""
    from pathlib import Path

    views_dir = Path(__file__).resolve().parents[1] / "templates" / "views"
    for view_type, keys in VIEW_TYPE_REQUIREMENTS.items():
        path = views_dir / view_type.removeprefix("views/")
        source = path.read_text(encoding="utf-8")
        for key in keys:
            assert key in source, (
                f"`VIEW_TYPE_REQUIREMENTS[{view_type!r}]` lists {key!r} "
                f"but the template doesn't reference it. Either restore "
                f"the access or drop the key from the table."
            )
