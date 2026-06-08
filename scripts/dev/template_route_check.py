#!/usr/bin/env python3
"""Forbid hardcoded entity-collection paths AND bare anchors to gated
entities in Jinja templates.

Two rules in one script — both keep the URL/lock surface single-source:

1. **Hardcoded entity paths** (the systemic fix for #552): templates
   reference URL paths through the ``entity_url`` / ``entity_form_url``
   Jinja globals (defined in ``src/framework/rendering/route_urls.py``)
   so the entity registry is the single source of truth for resource
   URL shape. Stale links like ``/organizations/new`` (#550) can
   otherwise creep back in.

2. **Bare anchors to gated entities** (the systemic fix from PR after
   #1264): an ``<a href="{{ entity_url('X' ...) }}">`` where ``X``'s
   spec declares ``read_policy.lock_reason`` MUST instead go through
   the ``entity_link('X', label, …)`` macro from
   ``_shared/_locked.html``. Otherwise the visible affordance can
   disagree with the destination's ``read_policy.assert_can_read`` —
   the bug ``/users/me`` → ``< Users`` → 403 demonstrated. ``entity_link``
   itself uses ``entity_url`` internally; the lint exempts that file.

What the lint flags
-------------------

Rule 1 — string literals whose **first path segment** matches the
URL-collection of any registered top-level entity. Examples:

  ``href="/posts/form"``                — flagged (rule 1)
  ``href="/organizations/{{ id }}"``    — flagged (rule 1)
  ``"/users/me"`` in any context        — flagged (rule 1)
  ``href="?kind=referral"``             — not flagged
  ``"/licensures"`` (sub of clinician)  — not flagged (not top-level)

Rule 2 — ``<a … href="…entity_url('GATED'…)…">`` where GATED is an
entity whose spec carries ``read_policy.lock_reason``. Examples:

  ``<a href="{{ entity_url('user') }}">Users</a>``         — flagged (rule 2)
  ``<a href="{{ entity_url('clinician', id=c.id) }}">…</a>`` — flagged
  ``<a href="{{ entity_url('post') }}">Posts</a>``         — not flagged
                                                             (post has no read_policy)
  ``{{ entity_link('user', 'Users') }}``                   — not flagged
                                                             (macro path)

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

    Owned subentities (clinician credentials) have ``url_collection``
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


def _load_gated_entities() -> set[str]:
    """Entity names whose specs declare ``ReadPolicy.lock_reason``.

    These are the entities for which an ``<a href="{{ entity_url(...) }}">``
    needs to flow through the ``entity_link`` macro so the visible
    affordance stays in sync with the route-level read guard. Today:
    ``user`` and ``clinician``; new entries appear automatically when
    a spec sets ``read_policy.lock_reason=REASON_*``.
    """
    sys.path.insert(0, str(_REPO_ROOT))
    import src.domain.routes  # noqa: F401 — side-effect import
    from src.framework.dispatch.registry import entity_registry

    return {
        spec.name
        for spec in entity_registry.specs()
        if spec.read_policy is not None and spec.read_policy.lock_reason is not None
    }


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


# Rule 2: `<a … href=…entity_url('X')…>` where X is gated AND the call has
# no extra args (no `id=`, no `subresource=`). The read-policy gate fires
# on the **collection list** path (`_list` / `_count` in `BaseRepository`),
# not on detail (`_get_by_id`), forms, or subresources. So a link to
# `/clinicians/form`, `/clinicians/{id}`, or `/users/me` doesn't 403 on
# the read policy — only `entity_url('clinician')` (the bare collection)
# does. The lint is scoped to match exactly that surface.
#
# `entity_form_url(...)` is never flagged: it produces `/X/form` or
# `/X/{id}/form`, both of which skip the read-policy gate.
_ANCHOR_OPEN_RE = re.compile(r"<a\b[^>]*?>", re.IGNORECASE | re.DOTALL)
_ENTITY_URL_BARE_COLLECTION_RE = re.compile(
    r"\bentity_url\(\s*['\"]([a-z_]+)['\"]\s*\)",
)

# The lint exempts the file where `entity_link` itself is defined —
# the macro internally renders an `<a href="{{ entity_url(...) }}">` and
# that's the sanctioned path. Any other template that hardcodes the
# pattern is the wrong shape.
_LINT_EXEMPT_FILES = {"_shared/_locked.html"}


def _bare_anchor_violations(
    path: Path, gated: set[str]
) -> list[tuple[Path, int, str, str]]:
    """Return (path, lineno, entity_name, snippet) for each bare anchor
    pointing at a gated entity in this file. Empty when the file is
    exempt or no gated anchor appears."""
    try:
        rel: Path = path.relative_to(_REPO_ROOT)
    except ValueError:
        rel = path
    rel_from_templates = None
    for root in _TEMPLATE_ROOTS:
        try:
            rel_from_templates = path.relative_to(root).as_posix()
            break
        except ValueError:
            continue
    if rel_from_templates is not None and rel_from_templates in _LINT_EXEMPT_FILES:
        return []

    text = _strip_comments(path.read_text(encoding="utf-8"))
    flat = text.replace("\n", " ")
    # Map flat-offset → original line so we can report a useful line number.
    offset_to_line: list[int] = []
    line = 1
    for ch in text:
        if ch == "\n":
            line += 1
            offset_to_line.append(line)
        else:
            offset_to_line.append(line)

    out: list[tuple[Path, int, str, str]] = []
    # Re-walk the original text to keep offset_to_line aligned. The flat
    # string substitutes ' ' for '\n' at the same indices, so positions match.
    flat_for_match = text.replace("\n", " ")
    for m in _ANCHOR_OPEN_RE.finditer(flat_for_match):
        snippet = m.group(0)
        for call in _ENTITY_URL_BARE_COLLECTION_RE.finditer(snippet):
            entity_name = call.group(1)
            if entity_name in gated:
                lineno = (
                    offset_to_line[m.start()] if m.start() < len(offset_to_line) else 1
                )
                # Trim the snippet for the error report.
                shown = " ".join(snippet.split())
                if len(shown) > 120:
                    shown = shown[:117] + "..."
                out.append((rel, lineno, entity_name, shown))
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
    gated = _load_gated_entities()
    pattern = _build_pattern(collections)

    rule1: list[tuple[Path, int, str]] = []
    rule2: list[tuple[Path, int, str, str]] = []
    files = _iter_templates()
    for path in files:
        rule1.extend(_violations(path, pattern))
        rule2.extend(_bare_anchor_violations(path, gated))

    if rule1:
        print(
            f"❌ Found {len(rule1)} hardcoded entity URL"
            f"{'s' if len(rule1) != 1 else ''} in templates:\n"
        )
        for path, lineno, literal in rule1:
            rel = path.relative_to(_REPO_ROOT)
            print(f"  {rel}:{lineno}: {literal!r}")
        print(
            "\nUse `entity_url(name, *, id=None, subresource=None)` or "
            "`entity_form_url(name, *, id=None)` instead — see "
            "src/framework/rendering/route_urls.py.\n"
            "Known top-level entity collections: " + ", ".join(sorted(collections))
        )

    if rule2:
        print(
            f"\n❌ Found {len(rule2)} bare `<a>` anchor"
            f"{'s' if len(rule2) != 1 else ''} pointing at gated entit"
            f"{'ies' if len(rule2) != 1 else 'y'}:\n"
        )
        for rel, lineno, entity_name, snippet in rule2:
            print(f"  {rel}:{lineno}: -> '{entity_name}' :: {snippet}")
        print(
            "\nThese routes raise 403 for viewers who fail "
            "`read_policy.assert_can_read`, so the visible `<a>` must "
            "lock when the viewer can't follow it. Use the macro:\n\n"
            '  {% from "_shared/_locked.html" import entity_link %}\n'
            "  {{ entity_link('<name>', 'Label') }}\n\n"
            "It renders as `<a>` for viewers who pass, and as the locked "
            "popover trigger for those who don't.\n"
            "Gated entities (with `ReadPolicy.lock_reason` set): "
            + ", ".join(sorted(gated))
        )

    if rule1 or rule2:
        return 1

    print(f"✅ No hardcoded entity URLs in templates ({len(files)} files checked).")
    print(
        f"✅ No bare anchors to gated entities ({len(gated)} gated, "
        f"exempt: {', '.join(sorted(_LINT_EXEMPT_FILES)) or 'none'})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
