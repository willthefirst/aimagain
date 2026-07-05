"""Copy-style-guide conformance tests.

Every template under `src/domain/templates/` is scanned for forbidden
patterns the audit found in production. Adding a violation surfaces as
a test failure here rather than as a code-review note.

The rules pinned (see [`./README.md` § "Copy style guide"](README.md)
for the full statement of each):

  1. `help="Optional."` is forbidden — forms carry no visual
     required/optional indicator, and optionality is never announced in
     prose (help text describes the value, not its optionality).
  2. `help="Optional. ..."` (period-as-prose-prefix) is forbidden for
     the same reason.
  3. The app-internal abbreviation `Org` is forbidden in user-facing
     copy — `Organization` is the canonical noun.
  4. The deprecated `(root — no parent)` phrasing is gone — the
     standard blank-option label is `(no parent)`.
  5. The "Save X" submit-button vocabulary is unified to "Save changes"
     across every edit form.

The scan looks at literal text in `.html` files; conditional Jinja
that builds the string at runtime is out of scope (we don't try to
parse Jinja). That's fine — every forbidden pattern below appeared as
a literal in the pre-PR audit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES_ROOT = Path(__file__).resolve().parent


def _all_template_files() -> list[Path]:
    """Every `.html` template under `src/domain/templates/`."""
    return sorted(TEMPLATES_ROOT.rglob("*.html"))


@pytest.mark.parametrize(
    "pattern,explanation",
    [
        (
            r'help=["\']Optional\.?["\']',
            'help="Optional." announces optionality in prose — forms carry '
            "no required/optional indicator; help text describes the value",
        ),
        (
            r'help=["\']Optional\.\s',
            'help="Optional. ..." announces optionality in prose — use '
            "`required=False` and put the explanation in help= without the "
            '"Optional." prefix',
        ),
        (
            r"\(root — no parent\)",
            "use `(no parent)` — the `root` jargon is internal",
        ),
        (
            # Match the action-cluster submit label only when the
            # convention diverges. "Save practice details" / "Save
            # program" / etc. are all unified to "Save changes".
            r'actions\(\s*["\']Save (?:practice details|program|organization|clinician|opening|referral|intake)["\']',
            'edit forms use "Save changes" — see the copy style guide',
        ),
    ],
)
def test_no_forbidden_copy_patterns(pattern: str, explanation: str) -> None:
    """Scan every template for forbidden patterns. The parametrize
    expansion lets pytest report each violation against the rule that
    flagged it instead of a single bulk failure."""
    rx = re.compile(pattern)
    violations: list[str] = []
    for path in _all_template_files():
        text = path.read_text()
        for match in rx.finditer(text):
            # Compute 1-based line number for the violation report.
            line_no = text[: match.start()].count("\n") + 1
            rel = path.relative_to(TEMPLATES_ROOT.parents[2])
            violations.append(f"{rel}:{line_no}: {match.group(0)!r}")
    assert (
        not violations
    ), f"Forbidden copy pattern found ({explanation}):\n  " + "\n  ".join(violations)


def test_org_abbreviation_only_in_comments_or_code() -> None:
    """`Org` (capitalized abbreviation) shouldn't appear in user-facing
    text — `Organization` is the canonical noun. The scan ignores Jinja
    comments (`{# ... #}`) and HTML comments (`<!-- ... -->`); those
    are developer-facing and use the abbreviation freely. Also ignores
    `org_id`, `org.name`, etc. — the *attribute* name stays `org` for
    historical reasons.
    """
    # Strip Jinja comments + HTML comments so the scan is on rendered
    # text only. Anything left that matches "\bOrg\b" not followed by
    # `_` / `.` / `s` (forming "Org_id", "Org.name", "Orgs") is a
    # user-facing leak.
    jinja_comment = re.compile(r"\{#.*?#\}", re.DOTALL)
    html_comment = re.compile(r"<!--.*?-->", re.DOTALL)
    org_word = re.compile(r"\bOrg(?![_\.s])\b")
    violations: list[str] = []
    for path in _all_template_files():
        text = path.read_text()
        text = jinja_comment.sub("", text)
        text = html_comment.sub("", text)
        for match in org_word.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            rel = path.relative_to(TEMPLATES_ROOT.parents[2])
            violations.append(f"{rel}:{line_no}: {match.group(0)!r}")
    assert (
        not violations
    ), "Use `Organization` (not `Org`) in user-facing copy:\n  " + "\n  ".join(
        violations
    )
