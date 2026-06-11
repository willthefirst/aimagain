#!/usr/bin/env python3
"""Forbid raw HTML primitives in domain templates.

The component-library rule (#1193): every list-card body, detail-page
card, form, action button, and similar affordance must compose macros
from ``src/framework/templates/_shared/`` instead of hand-rolling the
underlying HTML element. Hand-rolling means the visual / behavioral
vocabulary drifts and the next reader has to grep for which page
spells ``Cancel`` which way.

This check enforces the rule by scanning every ``.html`` file under
``src/domain/templates/`` and rejecting any of the forbidden raw tags
listed below. Comments (``{# ... #}`` Jinja and ``<!-- ... -->`` HTML)
are stripped before scanning so a docstring that mentions
"``<article>``" doesn't trigger.

When a real call site genuinely doesn't fit any existing macro and
isn't worth promoting (e.g. a one-off onboarding surface that exists
in exactly one place and has no second consumer), add the file path
to ``ALLOWLIST`` below. The allowlist is the explicit, visible
exception register — adding to it is a deliberate "no useful macro
abstraction here" decision, not a default escape valve.

Layered against the existing ``template_imports_check.py`` (which
forbids cross-resource imports) — that one keeps the partials
graph honest; this one keeps the HTML vocabulary honest.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Files (relative to ``src/domain/templates/``) whose raw HTML is a
# documented carve-out, not a violation. Each entry should be a path
# the next reader can `grep` against without ambiguity. Use the
# trailing slash form for whole directories.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Component-library showcase: by definition contains every
        # primitive directly.
        "dev/components.html",
        # The auth flow opts out of the resource grammar entirely —
        # documented in `src/framework/templates/README.md`.
        "auth/",
        # Sign-out button uses a unique `hx-on::after-request` redirect
        # shim because fastapi-users' logout returns 204 with no
        # HX-Redirect; the wrapping admin `<article>` is a single-fact
        # panel without a `card`-macro shape.
        "users/detail.html",
        # The unverified-email inbox CTA is a bespoke onboarding
        # surface: provider deep-link + Resend in a load-bearing alert
        # panel. Single instance, no second consumer.
        "users/email_form.html",
        # Message-the-poster micro-form swaps itself in place on send;
        # the swap-self contract doesn't match `inline_add_form`.
        "posts/_shared/_message_form.html",
        # Capability-tree cards have a status badge inside the heading
        # band that the `picker` macro doesn't model.
        "users/access/capabilities/index.html",
    }
)

# Tags forbidden in domain templates. Each tag maps to the macro the
# template should use instead — emitted in the error message so the
# fix is obvious from the lint output.
FORBIDDEN: dict[str, str] = {
    "button": (
        "use `actions(...)` / `confirm_delete_button(...)` / "
        "`confirm_action_button(...)` / `favorite_toggle(...)` from "
        "`_shared/actions.html`"
    ),
    "form": (
        "use `entity_form(...)` / `form_with_errors(...)` / "
        "`inline_add_form(...)` from `_shared/forms.html` / "
        "`_shared/form_meta.html`"
    ),
    "input": (
        "use `text_field` / `select_field` / `checkbox_field` / etc. "
        "from `_shared/form_fields.html` "
        '(hidden inputs `<input type="hidden">` are allowed and '
        "skipped by this check)"
    ),
    "select": "use `select_field(...)` / `entity_select_field(...)` from `_shared/form_fields.html`",
    "fieldset": "use `form_section(...)` from `_shared/form_fields.html`",
    "article": (
        "use `card(...)` / `picker(...)` / "
        "`post_feed_row(...)` / `clinician_card(...)` from `_shared/`"
    ),
    "menu": (
        "use `page_toolbar(...)` from `_shared/_toolbar.html` "
        "(it emits the toolbar `<menu>`)"
    ),
    "dl": "use `facts_block()` from `_shared/sections.html`",
    "dt": "use `fact(...)` from `_shared/sections.html`",
    "dd": "use `fact(...)` from `_shared/sections.html`",
}

# Match Jinja `{# ... #}` and HTML `<!-- ... -->` comments. Used to
# strip docstring mentions of forbidden tags before the per-tag scan.
# `re.DOTALL` so multi-line docstring comments are removed in full.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Match `<input ... type="hidden" ...>` — the one input shape that's
# always allowed (it's structural form plumbing, not a user-visible
# control). The negative-lookahead in the input-tag pattern below
# could express the carve-out, but a post-match check on the captured
# tag-text is clearer to read and easier to extend.
_HIDDEN_INPUT_RE = re.compile(r'type\s*=\s*"hidden"', re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    tag: str
    suggestion: str
    snippet: str

    def message(self) -> str:
        return (
            f"{self.file}:{self.line}: raw `<{self.tag}>` in domain template — "
            f"{self.suggestion}\n    {self.snippet.strip()}"
        )


def _strip_comments(text: str) -> str:
    """Strip both Jinja and HTML comments. Returns text with comment
    spans replaced character-by-character: non-newline characters
    become spaces, newlines are preserved. That keeps line numbers
    (and the count of total lines) aligned with the original file
    so a multi-line docstring above a real violation doesn't shift
    the reported line number."""

    def _blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = _JINJA_COMMENT_RE.sub(_blank, text)
    text = _HTML_COMMENT_RE.sub(_blank, text)
    return text


def _is_allowed(rel_path: str) -> bool:
    """True iff this path is in ``ALLOWLIST`` (either exact match or
    under a listed directory prefix)."""
    if rel_path in ALLOWLIST:
        return True
    return any(
        entry.endswith("/") and rel_path.startswith(entry) for entry in ALLOWLIST
    )


def _find_tag_violations(stripped: str, original: str, file: Path) -> list[Violation]:
    """Scan ``stripped`` for forbidden opening tags. Use ``original``
    to extract the matched line's full text for the error snippet."""
    violations: list[Violation] = []
    original_lines = original.splitlines()
    for tag, suggestion in FORBIDDEN.items():
        # `(?<![\w-])<tag\b` requires a word boundary before the `<` so
        # `<articles>` doesn't trip the `article` check (none exist, but
        # the safety belt is cheap). `\b` after the tag name is the
        # right-side anchor.
        pattern = re.compile(rf"(?<![\w-])<{tag}\b", re.IGNORECASE)
        for m in pattern.finditer(stripped):
            line_no = stripped.count("\n", 0, m.start()) + 1
            snippet = (
                original_lines[line_no - 1]
                if 0 < line_no <= len(original_lines)
                else "(snippet unavailable)"
            )
            # Skip the hidden-input carve-out: walk forward in the
            # original up to the next `>` and check for type="hidden".
            if tag == "input":
                tag_end = original.find(">", m.start())
                if tag_end != -1 and _HIDDEN_INPUT_RE.search(
                    original[m.start() : tag_end + 1]
                ):
                    continue
            violations.append(
                Violation(
                    file=file,
                    line=line_no,
                    tag=tag,
                    suggestion=suggestion,
                    snippet=snippet,
                )
            )
    return violations


def find_violations(files: Iterable[Path], templates_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for file in files:
        try:
            rel = file.resolve().relative_to(templates_root.resolve()).as_posix()
        except ValueError:
            continue
        if _is_allowed(rel):
            continue
        text = file.read_text(encoding="utf-8")
        stripped = _strip_comments(text)
        violations.extend(_find_tag_violations(stripped, text, file))
    return violations


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    while here != here.parent:
        if (here / "pyproject.toml").exists():
            return here
        here = here.parent
    raise RuntimeError("Could not locate project root (no pyproject.toml found).")


def _domain_templates_root() -> Path:
    return _project_root() / "src" / "domain" / "templates"


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
        help=("Files or directories to check. Defaults to " "src/domain/templates/."),
    )
    args = parser.parse_args(argv)

    root = _domain_templates_root()
    files = _collect_files(args.paths, root)
    violations = find_violations(files, root)

    if violations:
        print("❌ Raw HTML primitives in domain templates:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nDomain templates must compose macros from "
            "`src/framework/templates/_shared/` instead of hand-rolling "
            "primitives. See `src/framework/templates/README.md` § "
            "'Shared macros'. To exempt a genuine one-off, add the file "
            "to `ALLOWLIST` in this script with a one-line justification.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✅ No raw HTML primitives in domain templates ({len(files)} files checked)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
