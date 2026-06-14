"""Drift guardrail for the self-hosted Lucide icon subset.

`lucide-icons.css` ships a hand-curated subset of the upstream Lucide
icon font (1,546 glyphs trimmed to the ~30 we actually use). Adding a
new `<i class="icon-NAME">` in a template — or a new icon token in an
enum value — without adding a matching `.icon-NAME:before` rule to
the CSS causes the glyph to render blank in production.

This test scans every `class="...icon-NAME..."` and `icon='NAME'` /
`icon="NAME"` reference in `src/` and asserts each NAME has a rule in
the CSS. The failure message points at the file + line so the fix is
mechanical (look up the codepoint upstream, add a sorted line, re-run).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# test file lives at src/framework/static/fonts/, so parents[3] is `src`,
# parents[4] is the repo root.
_HERE = Path(__file__).resolve()
SRC = _HERE.parents[3]
ROOT = _HERE.parents[4]
CSS = _HERE.parent / "lucide-icons.css"

# Hardcoded `<i class="...icon-NAME...">`.
_HTML_CLASS_RE = re.compile(r'class="[^"]*icon-([a-z][a-z0-9-]*)[^"]*"')
# `icon='NAME'` / `icon="NAME"` macro kwargs.
_KWARG_RE = re.compile(r"icon=['\"]([a-z][a-z0-9-]*)['\"]")
# Allowlist rules in the CSS: `.icon-NAME:before { content: "\..." }`.
_RULE_RE = re.compile(r"^\.icon-([a-z][a-z0-9-]*):before\b", re.MULTILINE)


def _collect_referenced_icon_names() -> set[str]:
    icons: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(SRC):
        # Skip caches.
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith((".html", ".py")):
                continue
            # Don't recurse into ourselves — the test file's docstring
            # contains the literal `icon-NAME` token as documentation.
            if fn == os.path.basename(__file__):
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            icons.update(_HTML_CLASS_RE.findall(text))
            icons.update(_KWARG_RE.findall(text))
    return icons


def _collect_bundled_icon_names() -> set[str]:
    text = CSS.read_text()
    return set(_RULE_RE.findall(text))


def test_every_referenced_icon_has_a_bundled_rule() -> None:
    referenced = _collect_referenced_icon_names()
    bundled = _collect_bundled_icon_names()
    missing = sorted(referenced - bundled)
    assert not missing, (
        "These icon names are referenced in templates/enums but have no "
        f"`.icon-NAME:before` rule in {CSS.relative_to(ROOT)}:\n  "
        + "\n  ".join(missing)
        + "\n\nLook up each codepoint in "
        "https://unpkg.com/lucide-static@0.471.0/font/lucide.css and "
        'add a `.icon-NAME:before { content: "\\HEX"; }` line.'
    )


# No dead-rules test on purpose: many bundled icons are referenced
# only as bare string tokens in `src/domain/models/enums.py` (e.g. the
# third element of `(slug, label, "shield-check")`), which would
# require a parser-level scan of every tuple literal to surface
# accurately. The missing-rules test above catches the failure mode
# that *actually* breaks production (a referenced icon with no CSS
# rule renders blank); dead rules are dead weight worth maybe ~150
# bytes per icon — pruning them is a periodic cleanup, not a CI
# contract.
