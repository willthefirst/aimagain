"""Tests for the locked-affordance macros in ``_shared/_locked.html``.

Four trigger macros render "you can't do/see this yet" chrome driven by the
closed ``capabilities.REASON_*`` vocab.  All four carry a
``data-locked-cta="{reason}"`` attribute; the locked-affordance JS in
``base.html`` uses that attribute to anchor and open the matching
``<div popover>``.

- ``locked_action`` — aria-disabled button for write affordances.
- ``locked_link``   — aria-disabled anchor for locked navigation links.
- ``locked_name``   — ghost button replacing a withheld identity name.
- ``locked_field``  — ghost button replacing a withheld data value.

``locked_popovers()`` renders one ``<div popover>`` per known reason;
this is tested to confirm IDs and fix-URL links wire up correctly.

The real ``capabilities`` module is registered as the ``capabilities``
Jinja global so assertions exercise the actual copy wiring exactly as a
page render would.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser

from src.domain.logic import capabilities


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(str(Path(__file__).resolve().parents[1]))
    env = Environment(loader=ChoiceLoader([stub, framework]))
    env.globals["capabilities"] = capabilities
    return env


def _render(snippet: str) -> str:
    return _make_env().from_string(snippet).render()


def _render_action(reason: str, label: str, **kwargs) -> str:
    kwarg_str = "".join(f", {k}={v!r}" for k, v in kwargs.items())
    return _render(textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_action -%}}
        {{{{ locked_action(capabilities.{reason}, {label!r}{kwarg_str}) }}}}
        """))


def _render_link(reason: str, label: str) -> str:
    return _render(textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_link -%}}
        {{{{ locked_link(capabilities.{reason}, {label!r}) }}}}
        """))


def _render_name(placeholder: str) -> str:
    return _render(textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_name -%}}
        {{{{ locked_name({placeholder!r}) }}}}
        """))


def _render_field(reason: str) -> str:
    return _render(textwrap.dedent(f"""\
        {{%- from "_shared/_locked.html" import locked_field -%}}
        {{{{ locked_field(capabilities.{reason}) }}}}
        """))


def _render_popovers() -> str:
    return _render(
        '{%- from "_shared/_locked.html" import locked_popovers -%}'
        "{{ locked_popovers() }}"
    )


# ---------------------------------------------------------------------------
# locked_action
# ---------------------------------------------------------------------------


def test_locked_action_renders_button_with_label() -> None:
    html = _render_action("REASON_NETWORK_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert "+ Post a referral" in button.text()


def test_locked_action_is_aria_disabled_not_html_disabled() -> None:
    """Uses aria-disabled so keyboard users can still focus and trigger the
    popover — html disabled removes the element from tab order entirely."""
    html = _render_action("REASON_NETWORK_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert button.attributes.get("aria-disabled") == "true"
    assert "disabled" not in button.attributes


def test_locked_action_carries_data_locked_cta() -> None:
    html = _render_action("REASON_NETWORK_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert (
        button.attributes.get("data-locked-cta")
        == capabilities.REASON_NETWORK_UNVERIFIED
    )


def test_locked_action_always_has_lock_icon() -> None:
    html = _render_action("REASON_NETWORK_UNVERIFIED", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert button.css_first("i.icon-lock") is not None


def test_locked_action_extra_class_appended_to_outline() -> None:
    html = _render_action("REASON_NETWORK_UNVERIFIED", "Email", extra_class="secondary")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    cls = button.attributes.get("class", "")
    assert "outline" in cls
    assert "secondary" in cls


def test_locked_action_no_tooltip_wrapper() -> None:
    """CTA is now a popover, not a data-tooltip — no wrapper span."""
    html = _render_action("REASON_NETWORK_UNVERIFIED", "+ Post a referral")
    assert "data-tooltip" not in html


# ---------------------------------------------------------------------------
# locked_link
# ---------------------------------------------------------------------------


def test_locked_link_renders_anchor_with_label() -> None:
    html = _render_link("REASON_NETWORK_UNVERIFIED", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert "View full profile" in a.text()


def test_locked_link_is_aria_disabled() -> None:
    html = _render_link("REASON_NETWORK_UNVERIFIED", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.attributes.get("aria-disabled") == "true"


def test_locked_link_carries_data_locked_cta() -> None:
    html = _render_link("REASON_NETWORK_UNVERIFIED", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.attributes.get("data-locked-cta") == capabilities.REASON_NETWORK_UNVERIFIED


def test_locked_link_has_lock_icon() -> None:
    html = _render_link("REASON_NETWORK_UNVERIFIED", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.css_first("i.icon-lock") is not None


def test_locked_link_has_no_href() -> None:
    """No href — the popover is the action; navigating to '#' would be wrong."""
    html = _render_link("REASON_NETWORK_UNVERIFIED", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert "href" not in a.attributes


# ---------------------------------------------------------------------------
# locked_name
# ---------------------------------------------------------------------------


def test_locked_name_renders_ghost_button_with_placeholder() -> None:
    html = _render_name("Dr. J. Doe")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert "Dr. J. Doe" in btn.text()


def test_locked_name_data_locked_cta_is_network_unverified() -> None:
    """Hardwired to REASON_NETWORK_UNVERIFIED — the caller doesn't choose."""
    html = _render_name("Dr. J. Doe")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert (
        btn.attributes.get("data-locked-cta") == capabilities.REASON_NETWORK_UNVERIFIED
    )


def test_locked_name_has_lock_icon() -> None:
    html = _render_name("Dr. J. Doe")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert btn.css_first("i.icon-lock") is not None


def test_locked_name_no_href_link() -> None:
    """Name no longer renders a fix-URL link — the popover carries the CTA."""
    html = _render_name("Dr. J. Doe")
    assert HTMLParser(html).css_first("a") is None


# ---------------------------------------------------------------------------
# locked_field
# ---------------------------------------------------------------------------


def test_locked_field_renders_ghost_button() -> None:
    html = _render_field("REASON_NETWORK_UNVERIFIED")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None


def test_locked_field_carries_data_locked_cta() -> None:
    html = _render_field("REASON_NETWORK_UNVERIFIED")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert (
        btn.attributes.get("data-locked-cta") == capabilities.REASON_NETWORK_UNVERIFIED
    )


def test_locked_field_has_lock_icon() -> None:
    html = _render_field("REASON_NETWORK_UNVERIFIED")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert btn.css_first("i.icon-lock") is not None


def test_locked_field_shows_redacted_placeholder() -> None:
    """Renders the redacted-dots span, not the raw fix_label."""
    html = _render_field("REASON_NETWORK_UNVERIFIED")
    span = HTMLParser(html).css_first(".locked-redacted")
    assert span is not None
    assert "•" in span.text()


def test_locked_field_no_href_link() -> None:
    """Field no longer renders a fix-URL link — the popover carries the CTA."""
    html = _render_field("REASON_NETWORK_UNVERIFIED")
    assert HTMLParser(html).css_first("a") is None


def test_locked_field_unknown_reason_falls_back_not_raises() -> None:
    """A stray reason renders the generic hub nudge instead of raising."""
    env = _make_env()
    template = (
        '{%- from "_shared/_locked.html" import locked_field -%}'
        '{{ locked_field("totally-not-a-reason") }}'
    )
    html = env.from_string(template).render()
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert btn.attributes.get("data-locked-cta") == "totally-not-a-reason"


# ---------------------------------------------------------------------------
# locked_popovers
# ---------------------------------------------------------------------------


def test_locked_popovers_renders_one_per_known_reason() -> None:
    html = _render_popovers()
    tree = HTMLParser(html)
    for reason in (
        capabilities.REASON_EMAIL_UNVERIFIED,
        capabilities.REASON_NETWORK_UNVERIFIED,
    ):
        div = tree.css_first(f"#locked-cta-{reason}")
        assert div is not None, f"missing popover for {reason}"
        assert "popover" in div.attributes


def test_locked_popovers_contain_fix_url_links() -> None:
    html = _render_popovers()
    tree = HTMLParser(html)
    for reason in (
        capabilities.REASON_EMAIL_UNVERIFIED,
        capabilities.REASON_NETWORK_UNVERIFIED,
    ):
        meta = capabilities.reason_meta(reason)
        div = tree.css_first(f"#locked-cta-{reason}")
        assert div is not None
        link = div.css_first("a")
        assert link is not None
        assert link.attributes.get("href") == meta.fix_url


def test_locked_popovers_contain_unlock_copy() -> None:
    html = _render_popovers()
    for reason in (
        capabilities.REASON_EMAIL_UNVERIFIED,
        capabilities.REASON_NETWORK_UNVERIFIED,
    ):
        meta = capabilities.reason_meta(reason)
        assert meta.unlock in html
