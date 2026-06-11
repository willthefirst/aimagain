#!/usr/bin/env python3
"""Forbid raw `<i class="icon-...">` adjacent to text content.

The icon-label gap is owned by one CSS rule — ``[class^="icon-"] {
margin-inline-end: 0.25em; }`` in ``base.html``. A stray whitespace
text-node between ``</i>`` and the label compounds on top of it and
visibly doubles the gap (#TBD). Worse, djlint's auto-formatter
**creates** that whitespace text-node when it splits a long start tag
across lines — so the bug class is "djlint reformats the file, the
visible spacing silently doubles, nobody notices until they squint."

This check enforces that every icon + text-label pair flows through
``icon_label(icon, label)`` from
``src/framework/templates/_shared/icon_label.html``, which is the one
place in the repo with the ``{# djlint:off #}`` escape hatch. The
allowlist below is for partials whose icon-adjacent content is genuinely
not a text label (e.g. a span wrapper carrying its own class for CSS
targeting) and would need a different macro shape to migrate.

What this check flags:
  ``<i class="icon-foo"></i>Label``  — flush text after icon
  ``<i class="icon-foo"></i> Label`` — literal-space text after icon
  ``<i class="icon-foo"></i>\\n  Label`` — newline+indent + text
  ``<i class="icon-foo"></i>{{ expr }}`` — flush expression

What it allows:
  ``<i class="icon-foo"></i><span>…</span>`` — next char is ``<`` (tag)
  ``<i class="icon-foo"></i>{% if … %}`` — next non-ws is ``{%`` (block)
  ``<i class="icon-foo"></i>`` — pure icon, nothing after
  ``<i class="icon-foo"></i></a>`` — flush parent close
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Files (relative to ``src/``) whose raw icon-adjacent content is a
# documented carve-out, not a violation. Use trailing-slash form for
# whole directories.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # The macro that owns the flush-adjacency contract — this is
        # the one place the raw pattern is legal.
        "framework/templates/_shared/icon_label.html",
        # Component-library showcase: by definition contains every
        # primitive directly.
        "domain/templates/dev/components.html",
    }
)

# Match `<i class="icon-...">...</i>` start-to-close. The class
# attribute can have other classes alongside `icon-...`; the icon
# class itself can carry a Jinja expression for the glyph name.
_ICON_RE = re.compile(
    r'<i\b[^>]*class="[^"]*\bicon-[^"\s]+[^"]*"[^>]*></i>',
    re.IGNORECASE,
)

# After the matched `</i>`, classify the next non-whitespace content.
# Anything not in `_ALLOWED_NEXT` is a violation.
_ALLOWED_NEXT = ("<", "{%", "{#")

# Strip Jinja `{# ... #}` and HTML `<!-- ... -->` comments before
# scanning so docstring mentions don't trip the check.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    snippet: str

    def message(self) -> str:
        return (
            f'{self.file}:{self.line}: raw `<i class="icon-..."></i>` '
            f"adjacent to a text label — use "
            f"`icon_label(icon, label)` from "
            f"`_shared/icon_label.html` instead.\n    "
            f"{self.snippet.strip()}"
        )


def _strip_comments(text: str) -> str:
    """Blank comment spans character-by-character so line numbers stay
    aligned with the original file."""

    def _blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = _JINJA_COMMENT_RE.sub(_blank, text)
    text = _HTML_COMMENT_RE.sub(_blank, text)
    return text


def _is_allowed(rel_path: str) -> bool:
    if rel_path in ALLOWLIST:
        return True
    return any(
        entry.endswith("/") and rel_path.startswith(entry) for entry in ALLOWLIST
    )


def _classify_next(stripped: str, end: int) -> str | None:
    """Return ``None`` if the content following ``</i>`` is allowed
    (next non-whitespace starts a tag or Jinja block, or is EOF).
    Return the violating excerpt otherwise."""
    rest = stripped[end:]
    rest_no_ws = rest.lstrip()
    if not rest_no_ws:
        return None
    for prefix in _ALLOWED_NEXT:
        if rest_no_ws.startswith(prefix):
            return None
    return rest_no_ws[:40]


def _find_violations_in_text(text: str, file: Path) -> list[Violation]:
    stripped = _strip_comments(text)
    violations: list[Violation] = []
    lines = text.splitlines()
    for m in _ICON_RE.finditer(stripped):
        if _classify_next(stripped, m.end()) is None:
            continue
        line_no = stripped.count("\n", 0, m.start()) + 1
        snippet = (
            lines[line_no - 1] if 0 < line_no <= len(lines) else "(snippet unavailable)"
        )
        violations.append(Violation(file=file, line=line_no, snippet=snippet))
    return violations


def find_violations(files: Iterable[Path], src_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for file in files:
        try:
            rel = file.resolve().relative_to(src_root.resolve()).as_posix()
        except ValueError:
            continue
        if _is_allowed(rel):
            continue
        text = file.read_text(encoding="utf-8")
        violations.extend(_find_violations_in_text(text, file))
    return violations


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    while here != here.parent:
        if (here / "pyproject.toml").exists():
            return here
        here = here.parent
    raise RuntimeError("Could not locate project root (no pyproject.toml found).")


def _src_root() -> Path:
    return _project_root() / "src"


def _collect_files(paths: list[str], default_root: Path) -> list[Path]:
    if not paths:
        return sorted(default_root.rglob("*.html")) if default_root.exists() else []
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
        help="Files or directories to check. Defaults to src/.",
    )
    args = parser.parse_args(argv)

    root = _src_root()
    files = _collect_files(args.paths, root)
    violations = find_violations(files, root)

    if violations:
        print("❌ Raw icon-adjacent text in templates:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nEvery icon + text-label pair must compose "
            "`icon_label(icon, label)` from "
            "`_shared/icon_label.html` so the one djlint:off "
            "escape hatch stays in one place. To exempt a genuine "
            "one-off, add the file to `ALLOWLIST` in this script.",
            file=sys.stderr,
        )
        return 1

    print(f"✅ No raw icon-adjacent text in templates ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
