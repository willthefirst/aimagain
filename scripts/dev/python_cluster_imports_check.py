#!/usr/bin/env python3
"""Forbid cross-cluster Python imports inside layered directories.

Companion to ``template_imports_check.py``: same rule, different file
type. A file under ``src/<layer>/<cluster>/`` may import from its own
cluster or from any parent-level (shared) module in the same layer; it
may NOT import from a sibling cluster directory in the same layer.

Today this applies to ``src/models/`` only. Models are pure data
shape — a model file in one cluster has no business importing
from a sibling cluster (FKs reference each other via SQLAlchemy
strings, not Python imports). The rule is strict here.

``src/domain/`` is intentionally NOT in this list: per-entity
handlers, repositories, and schemas legitimately reach across
clusters for shared types (e.g. ``users/handlers.py`` needs
``providers/repository.ProviderRepository`` to fetch a user's
providers). Handler-to-handler cross-cluster imports inside
``domain/`` are still discouraged, but the discipline rests on
code review, not this rule.

Imports we recognize:
  - absolute:  ``from src.<layer>.<cluster>.<file> import X``
  - relative:  ``from .<cluster>.<file> import X`` (file at layer root)
               ``from ..<cluster>.<file> import X`` (file at cluster level)
  - bare-package: ``from src.<layer>.<cluster> import X``

Cross-tree imports (e.g. ``from src.models.posts...`` inside
``src/domain/providers/``) are out of scope for this check — the
within-tree rule is what matches the templates rule.

Usage:
    python scripts/dev/python_cluster_imports_check.py            # check all clustered layers
    python scripts/dev/python_cluster_imports_check.py path/a ... # check specific files
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Layers whose direct subdirectories we treat as clusters. Each layer's
# parent-level files (anything not inside a cluster directory) are the
# shared tier. Add a layer here when it grows cluster directories.
_CLUSTERED_LAYERS = ("models",)


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    importer_layer: str
    importer_cluster: str
    target_cluster: str
    raw_import: str

    def message(self) -> str:
        return (
            f"{self.file}:{self.line}: `{self.raw_import.strip()}` "
            f"crosses cluster boundary inside src/{self.importer_layer}/ "
            f"({self.importer_cluster}/ → {self.target_cluster}/). "
            f"Hoist the shared piece to src/{self.importer_layer}/ "
            f"or fix the dependency direction."
        )


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    while here != here.parent:
        if (here / "pyproject.toml").exists():
            return here
        here = here.parent
    raise RuntimeError("Could not locate project root (no pyproject.toml found).")


def _layer_clusters(layer_root: Path) -> set[str]:
    """Direct subdirectories of layer_root that contain at least one .py file.

    Anything else at the parent level (loose .py files, __pycache__) isn't a
    cluster. We don't hardcode entity names — the directories *are* the
    entity registry.
    """
    clusters: set[str] = set()
    if not layer_root.is_dir():
        return clusters
    for entry in layer_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("__") or entry.name.startswith("."):
            continue
        if any(entry.rglob("*.py")):
            clusters.add(entry.name)
    return clusters


def _file_position(file: Path, src_root: Path) -> tuple[str, str | None]:
    """Return (layer, cluster) for a file under src/, or (layer, None) if at parent.

    Files outside any clustered layer return ("", None) and are skipped by callers.
    """
    try:
        rel = file.resolve().relative_to(src_root.resolve())
    except ValueError:
        return ("", None)
    parts = rel.parts
    if len(parts) < 2:
        return ("", None)
    layer = parts[0]
    if layer not in _CLUSTERED_LAYERS:
        return ("", None)
    if len(parts) == 2:
        return (layer, None)  # File at layer root — parent-level shared.
    return (layer, parts[1])


# Patterns we recognize. Group 1 captures the layer-or-relative-marker;
# group 2 captures what comes after.
_ABS_RE = re.compile(
    r"^\s*from\s+src\.(\w+)\.(\w+)(?:\.\w+)*\s+import\b",
)
_REL_RE = re.compile(
    r"^\s*from\s+(\.+)(\w+)(?:\.\w+)*\s+import\b",
)


def _check_file(
    file: Path,
    layer: str,
    cluster: str,
    layer_clusters: set[str],
) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, raw in enumerate(
        file.read_text(encoding="utf-8").splitlines(), start=1
    ):
        m = _ABS_RE.match(raw)
        if m:
            target_layer, target_cluster = m.group(1), m.group(2)
            if target_layer != layer:
                continue  # Cross-layer — out of scope.
            if target_cluster not in layer_clusters:
                continue  # Target is a parent-level shared file, not a cluster.
            if target_cluster == cluster:
                continue  # Same cluster — fine.
            violations.append(
                Violation(file, lineno, layer, cluster, target_cluster, raw)
            )
            continue

        m = _REL_RE.match(raw)
        if m:
            dots, target_cluster = m.group(1), m.group(2)
            # `from .X import` from a file at <layer>/<cluster>/ resolves to
            # <layer>/<cluster>/X — that's a same-cluster sibling, not cross-cluster.
            # `from ..X import` from a file at <layer>/<cluster>/ resolves to
            # <layer>/X — possibly another cluster.
            if len(dots) == 1:
                continue  # Same-cluster sibling — fine.
            if len(dots) == 2:
                if target_cluster not in layer_clusters:
                    continue
                if target_cluster == cluster:
                    continue
                violations.append(
                    Violation(file, lineno, layer, cluster, target_cluster, raw)
                )
            # 3+ dots would walk above the layer — out of scope for the
            # within-layer rule, and Python won't resolve it anyway in this
            # tree (src is not a package).
    return violations


def find_violations(
    files: Iterable[Path],
    src_root: Path,
) -> list[Violation]:
    cluster_cache: dict[str, set[str]] = {}
    violations: list[Violation] = []
    for file in files:
        layer, cluster = _file_position(file, src_root)
        if not layer or cluster is None:
            continue
        if layer not in cluster_cache:
            cluster_cache[layer] = _layer_clusters(src_root / layer)
        violations.extend(_check_file(file, layer, cluster, cluster_cache[layer]))
    return violations


def _collect_files(paths: list[str], src_root: Path) -> list[Path]:
    if not paths:
        files: list[Path] = []
        for layer in _CLUSTERED_LAYERS:
            files.extend(sorted((src_root / layer).rglob("*.py")))
        return files
    out: list[Path] = []
    for raw in paths:
        p = Path(raw).resolve()
        if p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
        elif p.suffix == ".py":
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to check. Defaults to all clustered layers.",
    )
    args = parser.parse_args(argv)

    src_root = _project_root() / "src"
    files = _collect_files(args.paths, src_root)
    violations = find_violations(files, src_root)

    if violations:
        print("❌ Cross-cluster Python imports found:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nA shared piece belongs at the layer's parent level "
            "(e.g. src/framework/audit.py, src/models/enums.py). See "
            "src/README.md → 'Domain entities and the cluster pattern'.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ No cross-cluster Python imports ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
