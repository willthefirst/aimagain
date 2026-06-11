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

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.domain.logic import capabilities
from src.framework.templates._test_env import make_test_env


def _make_env() -> Environment:
    return make_test_env()


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
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert "+ Post a referral" in button.text()


def test_locked_action_is_aria_disabled_not_html_disabled() -> None:
    """Uses aria-disabled so keyboard users can still focus and trigger the
    popover — html disabled removes the element from tab order entirely."""
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert button.attributes.get("aria-disabled") == "true"
    assert "disabled" not in button.attributes


def test_locked_action_carries_data_locked_cta() -> None:
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert (
        button.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )


def test_locked_action_always_has_lock_icon() -> None:
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert button.css_first("i.icon-lock") is not None


def test_locked_action_label_is_flush_against_icon() -> None:
    """Regression: the icon-label gap is owned by CSS `margin-inline-end`. A
    stray whitespace text-node between ``</i>`` and the label compounds on top
    of it and visibly doubles the gap. Pin the flush adjacency."""
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    assert "</i>+ Post a referral" in html


def test_locked_action_extra_class_appended_to_outline() -> None:
    html = _render_action(
        "REASON_NOT_A_VERIFIED_PROVIDER", "Email", extra_class="secondary"
    )
    button = HTMLParser(html).css_first("button")
    assert button is not None
    cls = button.attributes.get("class", "")
    assert "outline" in cls
    assert "secondary" in cls


def test_locked_action_no_tooltip_wrapper() -> None:
    """CTA is now a popover, not a data-tooltip — no wrapper span."""
    html = _render_action("REASON_NOT_A_VERIFIED_PROVIDER", "+ Post a referral")
    assert "data-tooltip" not in html


# ---------------------------------------------------------------------------
# locked_link
# ---------------------------------------------------------------------------


def test_locked_link_renders_anchor_with_label() -> None:
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert "View full profile" in a.text()


def test_locked_link_is_aria_disabled() -> None:
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.attributes.get("aria-disabled") == "true"


def test_locked_link_carries_data_locked_cta() -> None:
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert (
        a.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )


def test_locked_link_has_lock_icon() -> None:
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.css_first("i.icon-lock") is not None


def test_locked_link_label_is_flush_against_icon() -> None:
    """Regression: see ``test_locked_action_label_is_flush_against_icon``."""
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
    assert "</i>View full profile" in html


def test_locked_link_has_no_href() -> None:
    """No href — the popover is the action; navigating to '#' would be wrong."""
    html = _render_link("REASON_NOT_A_VERIFIED_PROVIDER", "View full profile")
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
    """Hardwired to REASON_NOT_A_VERIFIED_PROVIDER — the caller doesn't choose."""
    html = _render_name("Dr. J. Doe")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert (
        btn.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
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
    html = _render_field("REASON_NOT_A_VERIFIED_PROVIDER")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None


def test_locked_field_carries_data_locked_cta() -> None:
    html = _render_field("REASON_NOT_A_VERIFIED_PROVIDER")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert (
        btn.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )


def test_locked_field_has_lock_icon() -> None:
    html = _render_field("REASON_NOT_A_VERIFIED_PROVIDER")
    btn = HTMLParser(html).css_first("button.locked-ghost-btn")
    assert btn is not None
    assert btn.css_first("i.icon-lock") is not None


def test_locked_field_shows_redacted_placeholder() -> None:
    """Renders the redacted-dots span, not the raw fix_label."""
    html = _render_field("REASON_NOT_A_VERIFIED_PROVIDER")
    span = HTMLParser(html).css_first(".locked-redacted")
    assert span is not None
    assert "•" in span.text()


def test_locked_field_no_href_link() -> None:
    """Field no longer renders a fix-URL link — the popover carries the CTA."""
    html = _render_field("REASON_NOT_A_VERIFIED_PROVIDER")
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
        capabilities.REASON_NOT_A_VERIFIED_PROVIDER,
    ):
        div = tree.css_first(f"#locked-cta-{reason}")
        assert div is not None, f"missing popover for {reason}"
        assert "popover" in div.attributes


def test_locked_popovers_contain_fix_url_links() -> None:
    html = _render_popovers()
    tree = HTMLParser(html)
    for reason in (
        capabilities.REASON_EMAIL_UNVERIFIED,
        capabilities.REASON_NOT_A_VERIFIED_PROVIDER,
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
        capabilities.REASON_NOT_A_VERIFIED_PROVIDER,
    ):
        meta = capabilities.reason_meta(reason)
        assert meta.unlock in html


# ---------------------------------------------------------------------------
# entity_link
# ---------------------------------------------------------------------------


def _render_entity_link(
    name: str, label: str, lock_reason: str | None, **kwargs
) -> str:
    """Render the macro with stub `entity_lock_reason` + `entity_url` globals.

    `lock_reason=None` exercises the unlocked branch (plain <a>); a
    `REASON_*` value exercises the locked branch (`locked_link` chrome).
    """
    env = _make_env()
    env.globals["entity_lock_reason"] = lambda _name: lock_reason
    env.globals["entity_url"] = lambda _name, id=None: (
        f"/{_name}s/{id}" if id is not None else f"/{_name}s"
    )
    href = kwargs.get("href")
    href_arg = f", href={href!r}" if href else ""
    id_arg = f", id={kwargs['id']!r}" if kwargs.get("id") is not None else ""
    template = (
        '{%- from "_shared/_locked.html" import entity_link -%}'
        f"{{{{ entity_link({name!r}, {label!r}{href_arg}{id_arg}) }}}}"
    )
    return env.from_string(template).render()


def test_entity_link_unlocked_renders_plain_anchor() -> None:
    """No lock reason → plain `<a>` with `entity_url(name)` as href."""
    html = _render_entity_link("clinician", "Browse clinicians", None)
    a = HTMLParser(html).css_first("a")
    assert a is not None
    assert a.attributes.get("href") == "/clinicians"
    assert "Browse clinicians" in a.text()
    assert "locked-link" not in (a.attributes.get("class") or "")
    assert "data-locked-cta" not in a.attributes


def test_entity_link_locked_renders_locked_link_chrome() -> None:
    """Lock reason set → `locked_link` chrome (aria-disabled + data-locked-cta)."""
    html = _render_entity_link(
        "clinician", "Browse clinicians", capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert a.attributes.get("aria-disabled") == "true"
    assert (
        a.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    assert "href" not in a.attributes


def test_entity_link_unlocked_explicit_href_overrides_entity_url() -> None:
    """Pass `href=` to point at a precomputed URL (e.g. subresource)."""
    html = _render_entity_link("user", "Users", None, href="/users?filter=active")
    a = HTMLParser(html).css_first("a")
    assert a is not None
    assert a.attributes.get("href") == "/users?filter=active"


def test_entity_link_locked_ignores_explicit_href() -> None:
    """When locked, the href is suppressed — popover is the action."""
    html = _render_entity_link(
        "user", "Users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER, href="/users"
    )
    a = HTMLParser(html).css_first("a.locked-link")
    assert a is not None
    assert "href" not in a.attributes
