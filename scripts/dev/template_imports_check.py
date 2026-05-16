#!/usr/bin/env python3
"""Forbid cross-resource Jinja imports across the template tree.

Templates live in two roots:

- ``src/framework/templates/`` — ``base.html``, ``_shared/`` macros, and
  ``views/`` chrome. Framework-level files: importable from any domain
  entity; no cross-cluster constraint applies inside this root.
- ``src/domain/templates/<entity>/`` — per-entity pages. A template under
  ``<a>/`` may only reference: a root-level file (``base.html``), its own
  ``<a>/``, ``_shared/`` (the cross-resource macro library), or ``views/``
  (the generic list/detail/form chrome). Anything else belongs in
  ``_shared/`` (#206).

The check accepts ``files or directories``; with no args it scans both
roots.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Matches the four template-reference directives. The first capture group
# is the directive name (extends/include/from/import); the second is the
# referenced template path. ``re.DOTALL`` lets the directive span newlines,
# which Jinja allows.
_DIRECTIVE_RE = re.compile(
    r"\{%-?\s*(extends|include|from|import)\s+\"([^\"]+)\"",
    re.DOTALL,
)

# Directories under a templates root that any template may reference.
# `_shared/` is the cross-resource macro library; `views/` is the generic
# list/detail/form-new/form-edit chrome. Both are framework-level.
SHARED_DIRS = frozenset({"_shared", "views"})


@dataclass(frozen=True)
class Violation:
    file: Path
    directive: str
    referenced: str
    importing_dir: str
    referenced_dir: str

    def message(self) -> str:
        return (
            f'{self.file}: {{% {self.directive} "{self.referenced}" %}} '
            f"crosses resource boundary "
            f"({self.importing_dir}/ → {self.referenced_dir}/). "
            f"Relocate to src/framework/templates/_shared/."
        )


def _resource_dir_of(
    template_path: Path, templates_roots: Iterable[Path]
) -> str | None:
    """Return the immediate sub-directory under the matching root, or None for root files."""
    abs_path = template_path.resolve()
    for root in templates_roots:
        try:
            rel = abs_path.relative_to(root.resolve())
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) <= 1:
            return None  # File sits at a templates root (e.g. base.html).
        return parts[0]
    return None


def _referenced_dir(referenced: str) -> str | None:
    """Return the immediate prefix of a referenced template path, or None for root files."""
    if "/" not in referenced:
        return None
    return referenced.split("/", 1)[0]


def find_violations(
    template_files: Iterable[Path],
    templates_root: Path | Iterable[Path],
) -> list[Violation]:
    if isinstance(templates_root, Path):
        roots: list[Path] = [templates_root]
    else:
        roots = list(templates_root)
    violations: list[Violation] = []
    for file in template_files:
        importing_dir = _resource_dir_of(file, roots)
        if importing_dir is None:
            # Root-level templates (base.html) have no owning resource —
            # nothing to lint. They're shared by definition.
            continue
        if importing_dir in SHARED_DIRS:
            # Files under `_shared/` or `views/` are framework-level
            # chrome; they can reference anywhere under any root without
            # crossing a resource boundary (there's no resource to leave).
            continue
        text = file.read_text(encoding="utf-8")
        for match in _DIRECTIVE_RE.finditer(text):
            directive, referenced = match.group(1), match.group(2)
            referenced_dir = _referenced_dir(referenced)
            if referenced_dir is None:
                continue  # Root reference (e.g. "base.html").
            if referenced_dir == importing_dir:
                continue  # Same resource — fine.
            if referenced_dir in SHARED_DIRS:
                continue  # Framework-level chrome — fine.
            violations.append(
                Violation(
                    file=file,
                    directive=directive,
                    referenced=referenced,
                    importing_dir=importing_dir,
                    referenced_dir=referenced_dir,
                )
            )
    return violations


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    while here != here.parent:
        if (here / "pyproject.toml").exists():
            return here
        here = here.parent
    raise RuntimeError("Could not locate project root (no pyproject.toml found).")


def _default_templates_roots() -> list[Path]:
    root = _project_root()
    return [
        root / "src" / "framework" / "templates",
        root / "src" / "domain" / "templates",
    ]


def _collect_files(paths: list[str], templates_roots: list[Path]) -> list[Path]:
    if not paths:
        files: list[Path] = []
        for root in templates_roots:
            if root.exists():
                files.extend(sorted(root.rglob("*.html")))
        return files
    files = []
    for raw in paths:
        p = Path(raw).resolve()
        if p.is_dir():
            files.extend(sorted(p.rglob("*.html")))
        elif p.suffix == ".html":
            files.append(p)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "Files or directories to check. Defaults to "
            "src/framework/templates/ and src/domain/templates/."
        ),
    )
    args = parser.parse_args(argv)

    templates_roots = _default_templates_roots()
    files = _collect_files(args.paths, templates_roots)
    violations = find_violations(files, templates_roots)

    if violations:
        print("❌ Cross-resource template imports found:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nA shared partial belongs in src/framework/templates/_shared/. "
            "See issue #206 / src/framework/templates/README.md.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ No cross-resource template imports ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
