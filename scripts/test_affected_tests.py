"""Tests for `scripts/affected_tests.py`.

The selector is what makes `dev test --affected` safe to wire into the
pre-merge-queue CI tier — pin the contract here so a regression that
silently picks fewer tests surfaces as a red test, not as a missed
prod regression.
"""

from pathlib import Path

from .affected_tests import (
    BLAST_RADIUS,
    AffectedSelection,
    _hits_blast_radius,
    select_affected_tests,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def _project(tmp_path: Path, files: list[str]) -> Path:
    """Materialize a fake project tree so the selector's `.is_file` /
    `.is_dir` lookups hit real disk. Mirrors the actual repo layout
    closely enough that the same selector code runs against it."""
    for rel in files:
        _touch(tmp_path / rel)
    return tmp_path


def test_blast_radius_short_circuits_to_full_suite(tmp_path: Path):
    root = _project(tmp_path, ["pyproject.toml", "src/foo.py", "src/test_foo.py"])
    sel = select_affected_tests(["pyproject.toml", "src/foo.py"], root)
    assert sel.full_suite is True
    assert sel.paths == ()
    assert "pyproject.toml" in sel.reason


def test_blast_radius_matches_directory_prefix(tmp_path: Path):
    """`alembic/` should match `alembic/versions/abc.py`, not just the
    bare token. Prefix semantics are load-bearing — most blast-radius
    entries are directories."""
    root = _project(tmp_path, ["alembic/versions/abc.py"])
    assert _hits_blast_radius("alembic/versions/abc.py") == "alembic/"
    sel = select_affected_tests(["alembic/versions/abc.py"], root)
    assert sel.full_suite is True


def test_source_change_includes_sibling_tests(tmp_path: Path):
    """Editing `src/foo/bar.py` must pull in every `test_*.py` in
    `src/foo/` — the colocated-test convention from CLAUDE.md means
    those are the tests that exercise the changed module."""
    root = _project(
        tmp_path,
        [
            "src/foo/bar.py",
            "src/foo/test_bar.py",
            "src/foo/test_other.py",
            "src/foo/baz.py",  # untouched sibling source
            "src/elsewhere/test_unrelated.py",
        ],
    )
    sel = select_affected_tests(["src/foo/bar.py"], root)
    assert sel.full_suite is False
    assert set(sel.paths) == {"src/foo/test_bar.py", "src/foo/test_other.py"}


def test_test_file_change_includes_itself(tmp_path: Path):
    """Editing a `test_*.py` directly must include that file — and
    not pull in unrelated sibling tests just because they live in the
    same directory (would defeat the purpose of the selector)."""
    root = _project(
        tmp_path,
        ["src/foo/test_bar.py", "src/foo/test_other.py"],
    )
    sel = select_affected_tests(["src/foo/test_bar.py"], root)
    assert set(sel.paths) == {"src/foo/test_bar.py"}


def test_contract_tests_are_skipped(tmp_path: Path):
    """`tests/test_contract` runs in its own CI job (Playwright + browser
    install). The selector must not pull those into the pre-queue
    tier, even when a contract test file itself changed."""
    root = _project(tmp_path, ["tests/test_contract/test_pact.py"])
    sel = select_affected_tests(["tests/test_contract/test_pact.py"], root)
    assert sel.paths == ()
    assert sel.full_suite is False


def test_non_python_changes_select_nothing(tmp_path: Path):
    """A README-only PR resolves to "no affected tests". The CLI
    handler reads `paths==() and full_suite==False` as "skip pytest"."""
    root = _project(tmp_path, ["docs/README.md", "src/foo.py"])
    sel = select_affected_tests(["docs/README.md"], root)
    assert sel.full_suite is False
    assert sel.paths == ()


def test_blast_radius_wins_over_targeted_selection(tmp_path: Path):
    """Mixed change: a targeted file AND a blast-radius file. The
    blast-radius rule must win — running the targeted tests alone
    would skip the regressions a config change might cause elsewhere."""
    root = _project(
        tmp_path,
        ["src/framework/config.py", "src/foo/bar.py", "src/foo/test_bar.py"],
    )
    sel = select_affected_tests(["src/framework/config.py", "src/foo/bar.py"], root)
    assert sel.full_suite is True


def test_scripts_test_file_change_includes_itself(tmp_path: Path):
    """`scripts/` follows the same colocated-test convention as `src/`.
    Editing `scripts/foo.py` must pull in `scripts/test_foo.py` and
    siblings, same as a `src/` edit."""
    root = _project(
        tmp_path,
        ["scripts/foo.py", "scripts/test_foo.py", "scripts/test_other.py"],
    )
    sel = select_affected_tests(["scripts/foo.py"], root)
    assert set(sel.paths) == {"scripts/test_foo.py", "scripts/test_other.py"}


def test_missing_test_file_is_silently_dropped(tmp_path: Path):
    """If `src/foo/bar.py` changes but no `test_*.py` exists in
    `src/foo/`, the selector returns an empty selection (not an
    error). The CLAUDE.md "test coverage required" rule is enforced
    by a different gate (the Stop hook reminder, not this selector)."""
    root = _project(tmp_path, ["src/foo/bar.py"])
    sel = select_affected_tests(["src/foo/bar.py"], root)
    assert sel.full_suite is False
    assert sel.paths == ()


def test_selection_pytest_args_round_trip():
    """The `pytest_args()` helper is what the CLI hands to subprocess.
    Pin both directions: full_suite → no args; targeted → paths as-is."""
    full = AffectedSelection(paths=(), full_suite=True, reason="")
    assert full.pytest_args() == []

    targeted = AffectedSelection(
        paths=("src/a/test_x.py", "src/b/test_y.py"),
        full_suite=False,
        reason="",
    )
    assert targeted.pytest_args() == ["src/a/test_x.py", "src/b/test_y.py"]


def test_blast_radius_list_is_documented():
    """The BLAST_RADIUS list is part of the contract. Spot-check the
    entries the CI plan depends on so a future "clean up the list"
    PR has to justify removals against this test."""
    must_include = {
        "pyproject.toml",
        "alembic/",
        "src/framework/config.py",
        "src/framework/dispatch/",
        ".github/workflows/",
    }
    assert must_include.issubset(set(BLAST_RADIUS))
