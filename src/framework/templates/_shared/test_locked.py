"""Tests for the locked-affordance macros in ``_shared/_locked.html``.

Three macros render the consistent "you can't do/see this yet" chrome
driven by the closed ``capabilities.REASON_*`` vocab:

- ``locked_action`` — a *disabled, visible* control wrapped in a Pico
  tooltip. The tooltip carries the unlock copy; the button is non-submittable.
- ``locked_field`` — a lock icon + fix link in a tooltip wrapper, rendered
  in place of a withheld data value (e.g. full address).
- ``locked_name`` — a lock icon + placeholder name as a link in a tooltip
  wrapper, rendered in place of a withheld identity name.

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


def _render_action(reason: str, label: str) -> str:
    template = textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_action -%}}
        {{{{ locked_action(capabilities.{reason}, {label!r}) }}}}
        """)
    return _make_env().from_string(template).render()


def _render_field(reason: str) -> str:
    template = textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_field -%}}
        {{{{ locked_field(capabilities.{reason}) }}}}
        """)
    return _make_env().from_string(template).render()


# ---------------------------------------------------------------------------
# locked_action — disabled control in tooltip wrapper
# ---------------------------------------------------------------------------


def test_locked_action_renders_disabled_button_with_label() -> None:
    html = _render_action("REASON_CLAIM_A_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None, "expected a <button> for the gated action"
    assert "disabled" in button.attributes, "gated action must be disabled"
    assert button.text(strip=True) == "+ Post a referral"


def test_locked_action_tooltip_carries_unlock_copy() -> None:
    """Unlock copy is in the tooltip wrapper, not inline — so a refactor
    can't silently drop it or hard-code copy that drifts from the single source."""
    meta = capabilities.reason_meta(capabilities.REASON_CLAIM_A_UNVERIFIED)
    html = _render_action("REASON_CLAIM_A_UNVERIFIED", "+ Post a referral")
    assert meta.unlock in html, "unlock copy must appear in data-tooltip"
    # Fix link is NOT inside locked_action — the tooltip is enough.
    # (Users click the button's parent or navigate to capability page separately.)
    button = HTMLParser(html).css_first("button[disabled]")
    assert button is not None


# ---------------------------------------------------------------------------
# locked_field — placeholder for withheld data values
# ---------------------------------------------------------------------------


def test_locked_field_renders_fix_link_with_correct_href() -> None:
    """The fix link points at the capability page so the viewer knows
    exactly what unlocks the field."""
    html = _render_field("REASON_VIEW_UNVERIFIED")
    link = HTMLParser(html).css_first(".locked-field a")
    assert link is not None
    assert link.attributes.get("href") == capabilities.fix_url_for(
        capabilities.REASON_VIEW_UNVERIFIED
    )


def test_locked_field_tooltip_carries_unlock_copy() -> None:
    """Unlock text appears in the tooltip attribute, not inline."""
    meta = capabilities.reason_meta(capabilities.REASON_VIEW_UNVERIFIED)
    html = _render_field("REASON_VIEW_UNVERIFIED")
    assert meta.unlock in html
    span = HTMLParser(html).css_first(".locked-field")
    assert span is not None
    assert span.attributes.get("data-tooltip") == meta.unlock


def test_locked_field_unknown_reason_falls_back_not_raises() -> None:
    """A stray reason renders the generic hub nudge instead of raising."""
    env = _make_env()
    template = (
        '{%- from "_shared/_locked.html" import locked_field -%}'
        '{{ locked_field("totally-not-a-reason") }}'
    )
    html = env.from_string(template).render()
    link = HTMLParser(html).css_first(".locked-field a")
    assert link is not None
    assert link.attributes.get("href") == "/users/me"


def test_locked_field_no_button_rendered() -> None:
    """A field placeholder is read-only chrome — no interactive button."""
    html = _render_field("REASON_VIEW_UNVERIFIED")
    assert HTMLParser(html).css_first("button") is None
