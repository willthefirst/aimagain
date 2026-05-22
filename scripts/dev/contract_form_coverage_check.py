#!/usr/bin/env python3
"""Enforce: every literal-URL form template has a `ContractPair`.

The systemic prevention for the forgot-password bug class
(`/auth/forgot-password` was changed to take JSON, but the form was
left form-encoded — no contract pair flagged the mismatch, so the
bug shipped). The contract-test framework already verifies form ⇄
endpoint protocol agreement (see `tests/test_contract/README.md`);
this lint pins the rule that **every form** has a pair.

What it checks
--------------

For every `.html`/`.jinja` file under `src/domain/templates/` and
`src/framework/templates/`, find each `<form>` tag's submit URL. The
extractor only handles **literal URLs** — `hx-post="/auth/x"` or
`<form method="post" action="/auth/x">`. Forms whose URL is
template-driven (`hx-{{ method }}="{{ action }}"`, used by the
generic entity-form macros) are skipped: those flow through the
entity dispatch layer and are covered by the per-entity contract
pairs already in the manifest.

Each `(METHOD, URL)` collected from templates must appear in EITHER
`tests/test_contract/manifest.py:CONTRACT_PAIRS[*].endpoints` OR the
`FORMS_WITHOUT_PAIRS` allowlist below.

Why the allowlist
-----------------

Some endpoints are intentionally not contract-paired:

- `POST /auth/jwt/login` — fastapi-users' OAuth2 password flow is
  form-encoded by RFC, so there's no JSON contract to verify.
- `POST /auth/sign-out`, `POST /auth/resend-verify` — empty-body
  endpoints; nothing to pin beyond "the path exists".

The allowlist makes the exemption visible and justified, not silent.
Adding a new entry requires a one-line rationale.

Exit code 0 = clean; 1 = violations (prints them).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_ROOTS = (
    _REPO_ROOT / "src" / "domain" / "templates",
    _REPO_ROOT / "src" / "framework" / "templates",
)


# Permanent exemptions: endpoints that POST/PUT/PATCH/DELETE but
# intentionally don't have (and don't need) a Pact pair. Each entry's
# value is the rationale shown on lint failure if someone tries to
# remove it. Adding an entry requires a sentence-long justification.
FORMS_WITHOUT_PAIRS: dict[str, str] = {
    "POST /auth/jwt/login": (
        "fastapi-users OAuth2 password flow is form-encoded by RFC 6749; "
        "no JSON contract to verify."
    ),
    "POST /auth/sign-out": (
        "Empty-body endpoint that clears the session cookie. Nothing "
        "to pin beyond the path itself."
    ),
    "POST /auth/resend-verify": (
        "Empty-body endpoint that reads the user from the session and "
        "re-mints a verify token. Nothing to pin beyond the path."
    ),
}


@dataclass(frozen=True)
class FormSubmission:
    """One form's submit target, located for diagnostics."""

    file: Path
    line: int
    method: str  # POST / PUT / PATCH / DELETE
    url: str  # literal URL

    @property
    def key(self) -> str:
        return f"{self.method} {self.url}"


# Strip Jinja {# ... #} comments only — keep statements and
# expressions because we use them to detect dynamic URLs.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)

# Match a `<form ...>` opening tag and capture the attribute block.
_FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.IGNORECASE | re.DOTALL)

# Within a form's attributes:
#   hx-post="..." / hx-put / hx-patch / hx-delete
_HX_VERB_RE = re.compile(r'\bhx-(post|put|patch|delete)\s*=\s*"([^"]*)"', re.IGNORECASE)

# Or the bare-HTML pattern: <form method="post|put|patch|delete" action="...">
_METHOD_RE = re.compile(r'\bmethod\s*=\s*"(post|put|patch|delete)"', re.IGNORECASE)
_ACTION_RE = re.compile(r'\baction\s*=\s*"([^"]*)"', re.IGNORECASE)


_JINJA_STMT_OR_EXPR_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def _static_prefix(url: str) -> str:
    """Return the static prefix of a URL — everything before any
    Jinja statement / expression. Used to recover the routable path
    from URLs like `/auth/jwt/login{% if next %}?next={{ next }}{% endif %}`,
    whose static prefix is `/auth/jwt/login`."""
    m = _JINJA_STMT_OR_EXPR_RE.search(url)
    return url[: m.start()] if m else url


def _is_dynamic_url(url: str) -> bool:
    """True if the URL has no static prefix the lint can match on.
    A URL like `{{ entity_url('clinician') }}` has empty static
    prefix and is out of scope. `/auth/jwt/login{% if next %}...{% endif %}`
    has prefix `/auth/jwt/login` and is in scope."""
    prefix = _static_prefix(url)
    if not prefix.startswith("/"):
        return True
    if " ~ " in prefix:
        # `"/foo" ~ var` string concatenation — the part after the
        # prefix is dynamic. Treat the whole URL as dynamic.
        return True
    return False


def _line_of(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _scan_file(path: Path) -> Iterable[FormSubmission]:
    raw = path.read_text(encoding="utf-8")
    content = _JINJA_COMMENT_RE.sub(lambda m: " " * len(m.group(0)), raw)

    for form_match in _FORM_TAG_RE.finditer(content):
        attrs = form_match.group(1)
        line = _line_of(content, form_match.start())

        # Prefer htmx attributes since the codebase's chosen pattern
        # is `<form hx-post="...">`. If present, an htmx verb wins
        # over `method=`.
        hx_match = _HX_VERB_RE.search(attrs)
        if hx_match:
            verb, url = hx_match.group(1).upper(), hx_match.group(2)
            if _is_dynamic_url(url):
                continue
            base = _static_prefix(url).split("?", 1)[0]
            yield FormSubmission(file=path, line=line, method=verb, url=base)
            continue

        method_match = _METHOD_RE.search(attrs)
        action_match = _ACTION_RE.search(attrs)
        if method_match and action_match:
            verb = method_match.group(1).upper()
            url = action_match.group(1)
            if _is_dynamic_url(url):
                continue
            base = _static_prefix(url).split("?", 1)[0]
            yield FormSubmission(file=path, line=line, method=verb, url=base)


def _gather_submissions() -> list[FormSubmission]:
    out: list[FormSubmission] = []
    for root in _TEMPLATE_ROOTS:
        if not root.is_dir():
            continue
        for ext in ("*.html", "*.htm", "*.jinja", "*.jinja2"):
            for path in root.rglob(ext):
                out.extend(_scan_file(path))
    return out


_MANIFEST_PATH = _REPO_ROOT / "tests" / "test_contract" / "manifest.py"


def _load_manifest_endpoints() -> set[str]:
    """AST-parse the manifest source and collect every `endpoints=`
    tuple literal.

    Done via static analysis (not import) so the lint can run in a
    pre-commit hook's isolated venv without the manifest's heavy
    imports (pytest, pact, consumer-server stubs). The trade-off:
    dynamic `endpoints` (computed at import time) wouldn't be seen.
    The manifest's `endpoints` are always literal tuples by
    convention, so this restriction is real but acceptable.
    """
    import ast

    source = _MANIFEST_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Only `ContractPair(...)` constructor calls.
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr != "ContractPair":
            continue
        if isinstance(func, ast.Name) and func.id != "ContractPair":
            continue
        if not isinstance(func, (ast.Name, ast.Attribute)):
            continue
        for kw in node.keywords:
            if kw.arg != "endpoints":
                continue
            if not isinstance(kw.value, ast.Tuple):
                continue
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.add(elt.value)
    return out


def main() -> int:
    submissions = _gather_submissions()
    paired = _load_manifest_endpoints()
    allowlist = set(FORMS_WITHOUT_PAIRS)

    violations: list[FormSubmission] = []
    for sub in submissions:
        if sub.key in paired:
            continue
        if sub.key in allowlist:
            continue
        violations.append(sub)

    if not violations:
        n = len(submissions)
        print(
            f"✅ Contract-form coverage: {n} literal-URL form submission(s) all covered."
        )
        return 0

    print(f"❌ Contract-form coverage: {len(violations)} uncovered submission(s).")
    print()
    for v in violations:
        try:
            shown = v.file.relative_to(_REPO_ROOT)
        except ValueError:
            shown = v.file
        print(f"📄 {shown}:{v.line}")
        print(f"   Submits: {v.key}")
        print(
            f"   No matching entry in tests/test_contract/manifest.py:CONTRACT_PAIRS[*].endpoints"
        )
        print(f"   and not in FORMS_WITHOUT_PAIRS allowlist.")
        print()
    print("Options (pick one, deliberately):")
    print('  • Add `endpoints=("<METHOD> <URL>",)` to an existing/new ContractPair')
    print("    in `tests/test_contract/manifest.py` and write the Pact pair.")
    print("    See tests/test_contract/README.md for the pattern.")
    print("  • Add the `<METHOD> <URL>` key to FORMS_WITHOUT_PAIRS in")
    print(f"    `scripts/dev/contract_form_coverage_check.py` with a one-line")
    print('    rationale (e.g. "empty body, nothing to pin").')
    return 1


if __name__ == "__main__":
    sys.exit(main())
