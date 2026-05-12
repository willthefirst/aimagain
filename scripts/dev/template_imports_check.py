#!/usr/bin/env python3
"""Forbid cross-resource Jinja imports in src/domain/templates/.

A template under ``src/domain/templates/<a>/`` may reference templates under:
  - the project root (e.g. ``base.html``)
  - its own directory ``<a>/...``
  - ``_shared/...``

Anything else — e.g. ``providers/edit.html`` doing ``{% from "posts/_form_macros.html" %}``
— is a layering smell. The shared partial belongs in ``_shared/``; tracking issue #206.

Recognized directives: ``{% extends "..." %}``, ``{% include "..." %}``,
``{% from "..." import ... %}``, ``{% import "..." as ... %}``.

Usage:
    python scripts/dev/template_imports_check.py                # check all
    python scripts/dev/template_imports_check.py path/a path/b  # check specific files
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

SHARED_DIR = "_shared"


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
            f"Relocate to src/domain/templates/{SHARED_DIR}/."
        )


def _resource_dir_of(template_path: Path, templates_root: Path) -> str | None:
    """Return the immediate sub-directory under templates_root, or None for root files."""
    try:
        rel = template_path.relative_to(templates_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) <= 1:
        return None  # File sits at templates_root (e.g. base.html).
    return parts[0]


def _referenced_dir(referenced: str) -> str | None:
    """Return the immediate prefix of a referenced template path, or None for root files."""
    if "/" not in referenced:
        return None
    return referenced.split("/", 1)[0]


def find_violations(
    template_files: Iterable[Path],
    templates_root: Path,
) -> list[Violation]:
    violations: list[Violation] = []
    for file in template_files:
        importing_dir = _resource_dir_of(file, templates_root)
        if importing_dir is None:
            # Root-level templates (base.html) have no owning resource —
            # nothing to lint. They're shared by definition.
            continue
        text = file.read_text(encoding="utf-8")
        for match in _DIRECTIVE_RE.finditer(text):
            directive, referenced = match.group(1), match.group(2)
            referenced_dir = _referenced_dir(referenced)
            if referenced_dir is None:
                continue  # Root reference (e.g. "base.html").
            if referenced_dir == importing_dir:
                continue  # Same resource — fine.
            if referenced_dir == SHARED_DIR:
                continue  # Shared — fine.
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


def _default_templates_root() -> Path:
    return _project_root() / "src" / "domain" / "templates"


def _collect_files(paths: list[str], templates_root: Path) -> list[Path]:
    if not paths:
        return sorted(templates_root.rglob("*.html"))
    files: list[Path] = []
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
        help="Files or directories to check. Defaults to src/domain/templates/.",
    )
    args = parser.parse_args(argv)

    templates_root = _default_templates_root()
    files = _collect_files(args.paths, templates_root)
    violations = find_violations(files, templates_root)

    if violations:
        print("❌ Cross-resource template imports found:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nA shared partial belongs in src/domain/templates/_shared/. "
            "See issue #206 / src/domain/templates/README.md.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ No cross-resource template imports ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
