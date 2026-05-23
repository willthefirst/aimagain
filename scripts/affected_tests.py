"""Pick which pytest files are worth running for a given changeset.

Used by `dev test --affected`. The two-tier CI plan uses this in the
pre-merge-queue tier to skip ~95% of the suite on single-file PRs;
the merge-queue tier still runs the full suite as the correctness gate
before main, so a false negative here is recoverable.

Conservative on purpose: a false positive (running too many tests)
costs CI minutes; a false negative (missing a regression) costs trust.
When in doubt, fall back to the full suite.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Files whose blast radius is too wide to map to specific tests.
# Any change to a path equal to OR prefixed by one of these → run the
# full suite. Prefix-only because we never need glob semantics here —
# everything in the list is either a single file or a directory path.
BLAST_RADIUS: tuple[str, ...] = (
    "pyproject.toml",
    "alembic/",
    "conftest.py",
    "tests/conftest.py",
    "src/main.py",
    "src/db.py",
    "src/auth_config.py",
    "src/framework/config.py",
    "src/framework/dispatch/",
    "src/framework/persistence/",
    "src/framework/observability/",
    "scripts/dev/",
    "scripts/dev_cli.py",
    ".github/workflows/",
    ".github/actions/",
)


@dataclass(frozen=True)
class AffectedSelection:
    """Outcome of `select_affected_tests`.

    `full_suite=True` means "no paths; pytest collects everything".
    Empty `paths` with `full_suite=False` means "no relevant tests
    exist — exit 0 without invoking pytest at all" (e.g. a docs-only
    PR).
    """

    paths: tuple[str, ...]
    full_suite: bool
    reason: str

    def pytest_args(self) -> list[str]:
        if self.full_suite:
            return []
        return list(self.paths)


def changed_files(base: str, project_root: Path) -> list[str]:
    """Return files changed in this branch vs `base`.

    Combines three sources so an in-progress local run sees the same
    set of files as a CI run on a pushed branch:
      - committed diffs (`base...HEAD`)
      - staged + unstaged working-tree diffs (`HEAD`)
      - untracked-but-not-ignored files (`ls-files --others`)

    Paths are returned relative to `project_root`, sorted.
    """
    out: set[str] = set()

    def _capture(*args: str) -> None:
        try:
            res = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                check=False,
                cwd=project_root,
            )
        except FileNotFoundError:
            return
        for raw in res.stdout.splitlines():
            line = raw.strip()
            if line:
                out.add(line)

    _capture("diff", "--name-only", f"{base}...HEAD")
    _capture("diff", "--name-only", "HEAD")
    _capture("ls-files", "--others", "--exclude-standard")

    return sorted(out)


def _hits_blast_radius(path: str) -> str | None:
    for prefix in BLAST_RADIUS:
        if path == prefix or path.startswith(prefix):
            return prefix
    return None


def select_affected_tests(files: list[str], project_root: Path) -> AffectedSelection:
    """Map a list of changed files to a pytest invocation.

    Rules:
      1. Any file in `BLAST_RADIUS` → full suite.
      2. `tests/test_contract/...` → skipped (it has its own CI job).
      3. `tests/test_*.py` → included directly.
      4. `src/.../test_<name>.py` → included directly.
      5. `src/.../<name>.py` → include every `test_*.py` in the same
         directory (colocated-test convention from CLAUDE.md).
      6. Non-Python files (`.md`, `.html`, `.css`, ...) → ignored.
         A README-only PR resolves to no affected tests; pytest is
         skipped entirely.
    """
    for path in files:
        prefix = _hits_blast_radius(path)
        if prefix:
            return AffectedSelection(
                paths=(),
                full_suite=True,
                reason=f"blast-radius file changed: {path} (matched `{prefix}`)",
            )

    selected: set[str] = set()
    for path in files:
        if not path.endswith(".py"):
            continue
        if path.startswith("tests/test_contract"):
            continue

        p = Path(path)

        if path.startswith("tests/") and p.name.startswith("test_"):
            if (project_root / path).is_file():
                selected.add(path)
            continue

        if path.startswith("src/") or path.startswith("scripts/"):
            stem = p.name
            if stem.startswith("test_"):
                if (project_root / path).is_file():
                    selected.add(path)
                continue
            sibling_dir = project_root / p.parent
            if sibling_dir.is_dir():
                for sib in sibling_dir.iterdir():
                    if (
                        sib.is_file()
                        and sib.name.startswith("test_")
                        and sib.name.endswith(".py")
                    ):
                        selected.add(sib.relative_to(project_root).as_posix())

    if not selected:
        return AffectedSelection(
            paths=(),
            full_suite=False,
            reason=f"no Python source or test files in {len(files)} changed file(s)",
        )

    return AffectedSelection(
        paths=tuple(sorted(selected)),
        full_suite=False,
        reason=f"{len(selected)} test file(s) selected from {len(files)} changed",
    )
