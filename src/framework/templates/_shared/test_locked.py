"""Tests for the locked-affordance macros in ``_shared/_locked.html``.

The two macros render the consistent "you can't do/see this yet" chrome
driven by the closed ``capabilities.REASON_*`` vocab:

- ``locked_action`` — a *disabled, visible* control plus an unlock line.
  Pins that the control is non-submittable (``disabled``) and that the
  reason copy + fix link come from ``capabilities.reason_meta`` (not
  inline), so a refactor can't silently drop the disabled attribute or
  hard-code copy that drifts from the single source.
- ``locked_field`` — a placeholder that names a *withheld* value. Pins
  that the caller-supplied field NAME renders while no value is emitted
  (the macro is handed a label, never data — it cannot leak).

The real ``capabilities`` module is registered as the ``capabilities``
Jinja global so the assertions exercise the actual copy wiring, exactly
as a page render would.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser

from src.domain.logic import capabilities


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    env = Environment(loader=ChoiceLoader([stub, framework]))
    env.globals["capabilities"] = capabilities
    return env


def _render(macro: str, reason: str, label: str) -> str:
    template = textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import {macro} -%}}
        {{{{ {macro}(capabilities.{reason}, {label!r}) }}}}
        """)
    return _make_env().from_string(template).render()


# ---------------------------------------------------------------------------
# locked_action — disabled control + unlock line
# ---------------------------------------------------------------------------


def test_locked_action_renders_disabled_button_with_label() -> None:
    html = _render("locked_action", "REASON_CLAIM_A_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None, "expected a <button> for the gated action"
    assert "disabled" in button.attributes, "gated action must be disabled"
    assert button.text(strip=True) == "+ Post a referral"


def test_locked_action_shows_reason_copy_and_fix_link_from_capabilities() -> None:
    """Copy + link come from `reason_meta`, not inline — assert the exact
    strings the single source returns so drift is caught here."""
    meta = capabilities.reason_meta(capabilities.REASON_CLAIM_A_UNVERIFIED)
    html = _render("locked_action", "REASON_CLAIM_A_UNVERIFIED", "+ Post a referral")
    tree = HTMLParser(html)
    assert meta.unlock in html
    link = tree.css_first("a")
    assert link is not None
    assert link.attributes.get("href") == meta.fix_url
    assert meta.fix_label in link.text()


# ---------------------------------------------------------------------------
# locked_field — placeholder naming a withheld value
# ---------------------------------------------------------------------------


def test_locked_field_names_the_field_without_emitting_a_value() -> None:
    """The macro is handed the field NAME, never its value — it renders
    the name + unlock path and nothing resembling live data."""
    html = _render("locked_field", "REASON_EMAIL_UNVERIFIED", "Practice name")
    tree = HTMLParser(html)
    assert "Practice name" in html
    link = tree.css_first("a.locked-field a, .locked-field a")
    assert link is not None
    assert link.attributes.get("href") == capabilities.fix_url_for(
        capabilities.REASON_EMAIL_UNVERIFIED
    )
    # No interactive control: a field placeholder is read-only chrome.
    assert tree.css_first("button") is None


def test_locked_field_unknown_reason_falls_back_not_raises() -> None:
    """A stray reason renders the generic hub nudge instead of raising."""
    env = _make_env()
    template = (
        '{%- from "_shared/_locked.html" import locked_field -%}'
        '{{ locked_field("totally-not-a-reason", "Some field") }}'
    )
    html = env.from_string(template).render()
    link = HTMLParser(html).css_first(".locked-field a")
    assert link is not None
    assert link.attributes.get("href") == "/profile"


def test_locked_field_without_label_reads_just_hidden() -> None:
    """Inside an already-labeled row (a `<dl>` `<dt>` names the field) the
    placeholder omits the name and reads "Hidden — …" — no redundant
    "<field> hidden". The fix link still renders."""
    env = _make_env()
    template = (
        '{%- from "_shared/_locked.html" import locked_field -%}'
        "{{ locked_field(capabilities.REASON_VIEW_UNVERIFIED) }}"
    )
    html = env.from_string(template).render()
    placeholder = HTMLParser(html).css_first(".locked-field")
    assert placeholder is not None
    text = placeholder.text(strip=True)
    assert text.startswith("Hidden"), text
    assert "hidden" not in text.replace("Hidden", "", 1).lower(), text
    assert placeholder.css_first("a") is not None
