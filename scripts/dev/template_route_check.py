#!/usr/bin/env python3
"""Forbid hardcoded entity-collection paths in Jinja templates.

The systemic fix for #552: templates reference URL paths through the
``entity_url`` / ``entity_form_url`` Jinja globals (defined in
``src/framework/rendering/route_urls.py``) so the entity registry is
the single source of truth for resource URL shape. Without this rule,
stale links like ``/organizations/new`` (#550) can creep back in: a
hardcoded path doesn't get a compile-time check that a matching route
is mounted.

What the lint flags
-------------------

A string literal whose **first path segment** matches the URL-collection
of any registered top-level entity. Examples:

  ``href="/posts/form"``                — flagged
  ``href="/organizations/{{ id }}"``    — flagged (literal first segment)
  ``"/users/me"`` in any context        — flagged
  ``request.url.path == '/clinicians'``  — flagged
  ``href="?kind=referral"``      — not flagged (relative, no `/`)
  ``href="{{ entity_url('post') }}"``   — not flagged (no literal segment)
  ``"/licensures"`` (sub of clinician)  — not flagged (not top-level)

Jinja comments (``{# ... #}``) are stripped before scanning so docstring
examples in macro headers don't false-positive.

Exit code 0 = clean; 1 = violations found (prints them).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_ROOTS = (
    _REPO_ROOT / "src" / "domain" / "templates",
    _REPO_ROOT / "src" / "framework" / "templates",
)
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def _load_collections() -> set[str]:
    """Top-level collection names from the live entity registry.

    Adding a new top-level entity automatically extends the lint —
    no per-script update needed.

    Owned subentities (provider credentials) have ``url_collection``
    too, but their routes nest under the parent (no top-level path
    starts with ``/licensures``), so they're filtered out.
    """
    # Lazy import + ensure routes are loaded so the registry is populated.
    sys.path.insert(0, str(_REPO_ROOT))
    import src.domain.routes  # noqa: F401 — side-effect import
    from src.framework.dispatch.registry import entity_registry

    out: set[str] = set()
    for spec in entity_registry.specs():
        if spec.parent is not None:
            # Owned subentity — never appears as a top-level path segment.
            continue
        if spec.prefix_override is not None:
            seg = spec.prefix_override.lstrip("/").split("/", 1)[0]
            if seg:
                out.add(seg)
        else:
            out.add(spec.url_collection)
    return out


def _strip_comments(text: str) -> str:
    return _JINJA_COMMENT_RE.sub("", text)


def _build_pattern(collections: set[str]) -> re.Pattern[str]:
    """Match a string literal whose first path segment is a known
    collection. Single- or double-quoted; word-boundary after the
    collection name so ``/users_foo`` doesn't false-positive."""
    alt = "|".join(re.escape(c) for c in sorted(collections))
    return re.compile(rf"""(['"])(/(?:{alt})\b[^'"]*)(['"])""")


def _violations(path: Path, pattern: re.Pattern[str]) -> list[tuple[Path, int, str]]:
    text = _strip_comments(path.read_text(encoding="utf-8"))
    out: list[tuple[Path, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in pattern.finditer(line):
            out.append((path, lineno, m.group(2)))
    return out


def _iter_templates() -> list[Path]:
    files: list[Path] = []
    for root in _TEMPLATE_ROOTS:
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.html")))
    return files


def main() -> int:
    collections = _load_collections()
    pattern = _build_pattern(collections)

    all_violations: list[tuple[Path, int, str]] = []
    for path in _iter_templates():
        all_violations.extend(_violations(path, pattern))

    if all_violations:
        print(
            f"❌ Found {len(all_violations)} hardcoded entity URL"
            f"{'s' if len(all_violations) != 1 else ''} in templates:\n"
        )
        for path, lineno, literal in all_violations:
            rel = path.relative_to(_REPO_ROOT)
            print(f"  {rel}:{lineno}: {literal!r}")
        print(
            "\nUse `entity_url(name, *, id=None, subresource=None)` or "
            "`entity_form_url(name, *, id=None)` instead — see "
            "src/framework/rendering/route_urls.py.\n"
            "Known top-level entity collections: " + ", ".join(sorted(collections))
        )
        return 1

    print(
        f"✅ No hardcoded entity URLs in templates "
        f"({len(_iter_templates())} files checked)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
