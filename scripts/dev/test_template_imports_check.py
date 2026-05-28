"""Tests for scripts/dev/template_imports_check.py."""

from __future__ import annotations

from pathlib import Path

from scripts.dev.template_imports_check import find_violations


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_same_resource_import_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    a = _write(root / "posts" / "list.html", '{%- from "posts/_form.html" import x -%}')
    _write(root / "posts" / "_form.html", "")

    violations = find_violations([a], root)

    assert violations == []


def test_shared_import_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    a = _write(
        root / "clinicians" / "edit.html",
        '{% from "_shared/form_fields.html" import f %}',
    )
    _write(root / "_shared" / "form_fields.html", "")

    violations = find_violations([a], root)

    assert violations == []


def test_views_extends_is_allowed(tmp_path: Path) -> None:
    """`views/` is framework-level chrome; any entity may extend it."""
    root = tmp_path / "templates"
    a = _write(root / "clinicians" / "list.html", '{% extends "views/list.html" %}')
    _write(root / "views" / "list.html", "")

    violations = find_violations([a], root)

    assert violations == []


def test_two_template_roots_resolve_owning_resource(tmp_path: Path) -> None:
    """A file's owning resource is determined relative to whichever root
    contains it. Framework chrome under one root and entity templates under
    another should not flag each other."""
    framework_root = tmp_path / "framework"
    domain_root = tmp_path / "domain"
    framework_view = _write(
        framework_root / "views" / "list.html", '{% extends "base.html" %}'
    )
    _write(framework_root / "base.html", "")
    domain_page = _write(
        domain_root / "clinicians" / "list.html",
        '{% extends "views/list.html" %}\n'
        '{% from "_shared/_card.html" import card %}',
    )

    violations = find_violations(
        [framework_view, domain_page], [framework_root, domain_root]
    )

    assert violations == []


def test_views_files_can_reference_anywhere(tmp_path: Path) -> None:
    """`views/` itself is framework-level — files inside aren't policed."""
    root = tmp_path / "templates"
    a = _write(
        root / "views" / "list.html",
        '{% extends "base.html" %}\n'
        '{% from "_shared/list_page.html" import list_breadcrumb %}',
    )

    violations = find_violations([a], root)

    assert violations == []


def test_root_extends_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    a = _write(root / "clinicians" / "edit.html", '{% extends "base.html" %}')

    violations = find_violations([a], root)

    assert violations == []


def test_cross_resource_from_is_flagged(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    a = _write(
        root / "clinicians" / "edit.html", '{%- from "posts/_form.html" import f -%}'
    )

    violations = find_violations([a], root)

    assert len(violations) == 1
    v = violations[0]
    assert v.directive == "from"
    assert v.referenced == "posts/_form.html"
    assert v.importing_dir == "clinicians/"
    assert v.referenced_dir == "posts/"
    assert "clinicians/ → posts/" in v.message()
    assert "_shared/" in v.message()


def test_cross_resource_include_is_flagged(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    a = _write(
        root / "users" / "detail.html", '{% include "posts/_owner_actions.html" %}'
    )

    violations = find_violations([a], root)

    assert len(violations) == 1
    assert violations[0].directive == "include"


def test_cross_resource_extends_is_flagged(tmp_path: Path) -> None:
    """A child template extending another resource's template is the same smell."""
    root = tmp_path / "templates"
    a = _write(root / "users" / "list.html", '{% extends "clinicians/list.html" %}')

    violations = find_violations([a], root)

    assert len(violations) == 1
    assert violations[0].directive == "extends"


def test_cross_resource_import_directive_is_flagged(tmp_path: Path) -> None:
    """`{% import 'x' as y %}` is the same shape as `{% from %}` for layering purposes."""
    root = tmp_path / "templates"
    a = _write(root / "clinicians" / "new.html", '{% import "posts/_form.html" as f %}')

    violations = find_violations([a], root)

    assert len(violations) == 1
    assert violations[0].directive == "import"


def test_root_file_has_no_owning_resource(tmp_path: Path) -> None:
    """base.html sits at templates root and may reference anywhere."""
    root = tmp_path / "templates"
    a = _write(root / "base.html", '{% include "posts/_owner_actions.html" %}')

    violations = find_violations([a], root)

    assert violations == []


def test_directive_spanning_newlines_is_caught(tmp_path: Path) -> None:
    """Jinja allows directives to break across lines; the regex uses DOTALL."""
    root = tmp_path / "templates"
    body = '{%-\n  from\n  "posts/_form.html"\n  import f\n-%}'
    a = _write(root / "clinicians" / "edit.html", body)

    violations = find_violations([a], root)

    assert len(violations) == 1


def test_multiple_violations_in_one_file(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    body = (
        '{% from "posts/_form.html" import x %}\n'
        '{% include "users/_admin_actions.html" %}\n'
    )
    a = _write(root / "clinicians" / "edit.html", body)

    violations = find_violations([a], root)

    assert len(violations) == 2
    referenced = {v.referenced for v in violations}
    assert referenced == {"posts/_form.html", "users/_admin_actions.html"}
