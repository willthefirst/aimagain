#!/usr/bin/env python3
"""Forbid cross-resource Jinja imports across the template tree.

Templates live in two roots:

- ``src/framework/templates/`` — ``base.html``, ``_shared/`` macros, and
  ``views/`` chrome. Framework-level files: importable from any domain
  entity; no cross-cluster constraint applies inside this root.
- ``src/domain/templates/`` — per-entity pages. Domain clusters may nest:

  * Top-level clusters: ``<entity>/`` (e.g. ``providers/``, ``users/``).
  * Sub-cluster layout: ``<cluster>/<sub>/`` (e.g. ``posts/openings/``,
    ``posts/referrals/``). The cluster's ``_shared/`` partials live at
    ``<cluster>/_shared/``.

  A template at ``<a>/.../page.html`` may reference:

  * a root-level file (``base.html``),
  * any directory on its own ancestor chain (its own directory, its
    parent cluster, …, up to the templates root),
  * any ``_shared/`` directory on an ancestor's level (i.e.,
    ``<ancestor>/_shared/``),
  * ``views/`` (the generic list/detail/form chrome).

  In particular: sibling sub-clusters cannot reach into each other
  (``posts/openings/`` cannot import from ``posts/referrals/``), but a
  sub-cluster CAN import from its parent's shared partials
  (``posts/openings/`` → ``posts/_shared/``).

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

# Top-level directory names that any template may reference. `_shared/`
# and `views/` here are the *framework-root* shared dirs (under
# ``src/framework/templates/``). Per-cluster `_shared/` (e.g.
# ``posts/_shared/``) is handled by the sibling-shared rule below — they
# don't need to be listed here.
TOP_LEVEL_SHARED_DIRS = frozenset({"_shared", "views"})


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
            f"({self.importing_dir} → {self.referenced_dir}). "
            f"Relocate the partial to a shared dir on the importing "
            f"template's ancestor chain (e.g. <cluster>/_shared/ or "
            f"src/framework/templates/_shared/)."
        )


def _resource_path(
    template_path: Path, templates_roots: Iterable[Path]
) -> tuple[str, ...] | None:
    """Directory tuple under the matching root, excluding the filename.

    Returns ``()`` for a file sitting at a templates root (e.g.
    ``base.html``) and ``None`` if the file isn't under any root.
    """
    abs_path = template_path.resolve()
    for root in templates_roots:
        try:
            rel = abs_path.relative_to(root.resolve())
        except ValueError:
            continue
        return rel.parts[:-1]  # drop filename
    return None


def _referenced_path(referenced: str) -> tuple[str, ...]:
    """Directory tuple of the referenced template, excluding the filename.

    Returns ``()`` for a root-level reference (e.g. ``base.html``).
    """
    parts = referenced.split("/")
    return tuple(parts[:-1])


def _is_allowed(importing: tuple[str, ...], referenced: tuple[str, ...]) -> bool:
    """True iff a template at ``importing/<file>.html`` may reference
    a template at ``referenced/<file>.html``.

    Rules:
      1. Root reference (``referenced == ()``) is always allowed.
      2. Top-level framework chrome (``_shared/``, ``views/``) — any
         template may reach in.
      3. Same directory — always fine.
      4. Ancestor — ``referenced`` is a proper prefix of ``importing``.
         (A template in a sub-cluster may import from its parent
         cluster's directory: ``posts/openings/`` → ``posts/``.)
      5. Sibling ``_shared/`` — ``referenced`` ends in ``_shared`` AND
         its parent is a prefix of ``importing``. (A sub-cluster may
         import from its parent cluster's ``_shared/``:
         ``posts/openings/`` → ``posts/_shared/``.)
    """
    # Rule 1
    if referenced == ():
        return True
    # Rule 2: top-level framework shared dirs
    if referenced[0] in TOP_LEVEL_SHARED_DIRS and len(referenced) == 1:
        return True
    # Rule 3: same directory
    if importing == referenced:
        return True
    # Rule 4: referenced is a proper ancestor of importing
    if len(referenced) < len(importing) and importing[: len(referenced)] == referenced:
        return True
    # Rule 5: sibling `_shared/` on an ancestor's level
    if referenced and referenced[-1] == "_shared":
        ref_parent = referenced[:-1]
        if importing[: len(ref_parent)] == ref_parent:
            return True
    return False


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
        importing = _resource_path(file, roots)
        if importing is None:
            continue  # File outside any templates root.
        if importing == ():
            # Root-level template (e.g. base.html) — shared by definition.
            continue
        if importing[0] in TOP_LEVEL_SHARED_DIRS:
            # Files under top-level `_shared/` or `views/` are framework
            # chrome and can reference anywhere.
            continue
        text = file.read_text(encoding="utf-8")
        for match in _DIRECTIVE_RE.finditer(text):
            directive, referenced = match.group(1), match.group(2)
            referenced_parts = _referenced_path(referenced)
            if _is_allowed(importing, referenced_parts):
                continue
            violations.append(
                Violation(
                    file=file,
                    directive=directive,
                    referenced=referenced,
                    importing_dir="/".join(importing) + "/",
                    referenced_dir=(
                        ("/".join(referenced_parts) + "/")
                        if referenced_parts
                        else "<root>"
                    ),
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
            "\nA shared partial belongs in a shared dir on the importing "
            "template's ancestor chain (e.g. <cluster>/_shared/ or "
            "src/framework/templates/_shared/). See "
            "src/framework/templates/README.md.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ No cross-resource template imports ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
