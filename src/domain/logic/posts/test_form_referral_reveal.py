"""Parity tests tying the referral conditional-required registry to its
presentation layer (Option A: pure-CSS `:has()` reveal, server owns
"required").

`REFERRAL_CONDITIONAL_RULES` in `conditional_fields.py` is the single
source of truth for *which* referral field is conditional and on *what*.
Each rule exposes `rule.reveal_token` — a `"<trigger_field>:<value>"`
string (boolean triggers use `"true"`). That same token has to appear in
two presentation files for the reveal to actually work end-to-end:

  1. `templates/posts/_form_referral.html` — the
     `conditional_field("<token>")` wrapper around the dependent field,
     and
  2. `static/css/domain.css` — the per-token `:has()` reveal rule.

Rendering the full referral create form needs a logged-in user plus
clinician/affiliation fixtures (the practice picker reads
`current_user.clinicians`), which is heavy for a unit test. Instead we
assert each `reveal_token` is present as a literal in BOTH source files.
This pins template + CSS to the registry so adding/removing a rule
without updating both surfaces fails here rather than silently shipping a
field that never reveals (or reveals but isn't validated). It also pins
that the dependent fields carry no HTML `required` attribute (a hidden
required field would block submit) — enforced by scanning the template
source for the six dependent field names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.logic.posts.conditional_fields import REFERRAL_CONDITIONAL_RULES

# This file: src/domain/logic/posts/test_form_referral_reveal.py
# parents[4] = repo root.
_ROOT = Path(__file__).resolve().parents[4]
_FORM = _ROOT / "src/domain/templates/posts/_form_referral.html"
_CSS = _ROOT / "src/domain/static/css/domain.css"

_REVEAL_TOKENS = [r.reveal_token for r in REFERRAL_CONDITIONAL_RULES]
_DEPENDENT_FIELDS = [r.field for r in REFERRAL_CONDITIONAL_RULES]


@pytest.mark.parametrize("token", _REVEAL_TOKENS, ids=_REVEAL_TOKENS)
def test_reveal_token_present_in_form_template(token: str) -> None:
    """Every rule's `reveal_token` appears as a
    `conditional_field("<token>")` call in the referral form source."""
    source = _FORM.read_text()
    assert f'conditional_field("{token}")' in source, (
        f"reveal token {token!r} has no conditional_field(...) wrapper in "
        f"{_FORM} — the dependent field will never reveal."
    )


@pytest.mark.parametrize("token", _REVEAL_TOKENS, ids=_REVEAL_TOKENS)
def test_reveal_token_present_in_domain_css(token: str) -> None:
    """Every rule's `reveal_token` appears as a `data-reveal-when`
    selector in domain.css, so the wrapped field is actually revealed."""
    source = _CSS.read_text()
    assert f'data-reveal-when="{token}"' in source, (
        f"reveal token {token!r} has no `:has()` reveal rule in {_CSS} — "
        f"the wrapped field stays hidden even when its trigger is set."
    )


@pytest.mark.parametrize("field", _DEPENDENT_FIELDS, ids=_DEPENDENT_FIELDS)
def test_dependent_field_rendered_with_required_false(field: str) -> None:
    """Each dependent field is rendered with `required=false` in the
    form (so it emits no HTML `required` attr). A hidden+required field
    would block submit with a control the user can't see; requiredness
    is enforced server-side by `enforce_conditional_required`."""
    source = _FORM.read_text()
    # The field appears as the first positional arg of a *_field macro
    # call; the same line carries `required=false`.
    matching = [
        line
        for line in source.splitlines()
        if f'"{field}"' in line and "_field(" in line
    ]
    assert matching, f"dependent field {field!r} not rendered in {_FORM}"
    for line in matching:
        assert "required=false" in line, (
            f"dependent field {field!r} must be rendered with "
            f"required=false (no HTML required attr on a reveal-hidden "
            f"field). Offending line: {line.strip()!r}"
        )
