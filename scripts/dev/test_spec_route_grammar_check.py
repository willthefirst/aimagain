"""Tests for `scripts/dev/spec_route_grammar_check.py`.

The lint's job is to flag any `EntitySpec` whose `RouteSet` declares
mutation verbs (`create` / `update` / `delete`) without the matching
form/list pages — the canonical-resource-pattern drift that prompted
the slice-8 framework work.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.dev.spec_route_grammar_check import _check_spec


def _make_spec(name: str, **routes_flags) -> SimpleNamespace:
    """Fixture-light spec stub: just `name` + a `routes` carrier.

    `_check_spec` only reads `.name` and `.routes.<flag>`, so we don't
    need a real `EntitySpec` — that would drag in the full registration
    machinery for every test.
    """
    routes = SimpleNamespace(
        create=False,
        update=False,
        delete=False,
        list=False,
        detail=False,
        form_new=False,
        form_edit=False,
    )
    for k, v in routes_flags.items():
        setattr(routes, k, v)
    return SimpleNamespace(name=name, routes=routes)


def test_canonical_spec_passes():
    """A spec declaring the full canonical set (mutations + list +
    both form pages) has no violation."""
    spec = _make_spec(
        "widget",
        create=True,
        update=True,
        delete=True,
        list=True,
        form_new=True,
        form_edit=True,
    )
    assert _check_spec(spec) is None


def test_read_only_spec_passes():
    """A spec with only `list` / `detail` (no mutations) is fine —
    nothing implies form pages."""
    spec = _make_spec("readonly", list=True, detail=True)
    assert _check_spec(spec) is None


def test_create_without_form_new_is_flagged():
    """`create=True` without `form_new=True` is the canonical
    'inline create form on the list page' drift the lint catches."""
    spec = _make_spec("driftspec", create=True, list=True, form_edit=True)
    violation = _check_spec(spec)
    assert violation is not None
    assert "form_new" in violation.missing_verbs
    assert "create" in violation.implied_by


def test_update_without_form_edit_is_flagged():
    """`update=True` without `form_edit=True` mirrors the create case."""
    spec = _make_spec("driftspec", update=True, list=True, form_new=True)
    violation = _check_spec(spec)
    assert violation is not None
    assert "form_edit" in violation.missing_verbs
    assert "update" in violation.implied_by


def test_any_mutation_without_list_is_flagged():
    """Mutations need a list page to navigate back to (per the
    canonical pattern)."""
    spec = _make_spec(
        "driftspec",
        delete=True,
        form_new=True,
        form_edit=True,
    )
    violation = _check_spec(spec)
    assert violation is not None
    assert "list" in violation.missing_verbs
    assert "delete" in violation.implied_by


def test_multiple_missing_verbs_all_reported():
    """The current 4 clinician sub-resources fail every implication
    at once — the violation should name every gap so the user knows
    the full shape of the conversion ahead."""
    spec = _make_spec("driftspec", create=True, update=True, delete=True)
    violation = _check_spec(spec)
    assert violation is not None
    assert set(violation.missing_verbs) == {"form_new", "form_edit", "list"}


@pytest.mark.parametrize("verb", ["create", "update", "delete"])
def test_solo_mutation_flags_only_list_and_its_form(verb: str):
    """Each mutation verb pulls in its specific form requirement plus
    the shared `list` requirement — but not the form pages tied to
    *other* mutation verbs."""
    spec = _make_spec("driftspec", **{verb: True})
    violation = _check_spec(spec)
    assert violation is not None
    missing = set(violation.missing_verbs)
    assert "list" in missing
    if verb == "create":
        assert "form_new" in missing
        assert "form_edit" not in missing
    elif verb == "update":
        assert "form_edit" in missing
        assert "form_new" not in missing
    else:
        # delete pulls neither form requirement on its own
        assert "form_new" not in missing
        assert "form_edit" not in missing
