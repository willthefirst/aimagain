"""Tests for the shared support-contact macros (`_shared/support.html` +
`_shared/support.txt`).

This copy is the single source for the "reach us" sentence, the support
address, and the pre-filled `mailto:` — rendered in the site `<footer>`
(`base.html`) and in every transactional email (both the HTML and the text
part). Two contracts can silently break:

- the HTML part carries a real `<a href="mailto:...">` whose subject + body
  are URL-encoded so the draft opens ready to fill in;
- the text part is PLAIN text — no `<a>`, and no HTML-escaped entities. It
  lives in a `.txt` template precisely so it renders un-escaped; a leak would
  turn "isn't" into "isn&#39;t" in a plain-text email body.

Uses the production Jinja env (`templates.env`) so the html/txt autoescape
split under test is exactly what ships.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

from src.framework.rendering.templating import templates

SUPPORT_EMAIL = "help@bedlamconnect.com"


def _html_note() -> str:
    module = templates.env.get_template("_shared/support.html").module
    return str(module.support_note_html())


def _text_note() -> str:
    module = templates.env.get_template("_shared/support.txt").module
    return str(module.support_note_text())


def test_html_note_links_the_address_with_a_prefilled_mailto() -> None:
    link = HTMLParser(_html_note()).css_first("a")
    assert link is not None
    assert link.text() == SUPPORT_EMAIL
    href = link.attributes.get("href") or ""
    assert href.startswith(f"mailto:{SUPPORT_EMAIL}?")
    # Prefill: a subject plus a multi-line prompt body, both URL-encoded
    # (parse_qs decodes them back) so the compose window opens usable.
    params = parse_qs(urlparse(href).query)
    assert params["subject"][0]
    assert "\n" in params["body"][0]


def test_text_note_is_plain_text_with_the_bare_address() -> None:
    note = _text_note()
    assert SUPPORT_EMAIL in note
    assert "<" not in note  # no <a> — safe in a text/plain body
    assert "&#39;" not in note and "&amp;" not in note  # no autoescape leak
    assert "isn't" in note  # the apostrophe survives as a literal


def test_both_parts_share_one_lead_sentence() -> None:
    """Single source: the text part's sentence (minus the address) is the
    same lead the HTML part renders — so the two never drift."""
    html_text = HTMLParser(_html_note()).text()
    lead = _text_note().rsplit(SUPPORT_EMAIL, 1)[0].strip()
    assert lead
    assert lead in html_text
