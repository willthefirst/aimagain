"""Tests for the re-verify partial (`profile/_reverify.html`).

Re-verify mode is unreachable in production today — `claim_state()` always
returns `lapsed=()`, so `resolve_profile_mode` never picks it (it lands when
the Phase-3 recompute helpers detect a regression). These template-unit tests
render the partial directly with a stubbed `claim_state` so the lapsed-card
markup is pinned *now*, and assert it reads entirely from
`capabilities.reason_meta(...)` — the convergence this file exists to lock in:

- the card title, body copy, and Fix CTA all come from the single source,
  keyed by the same `REASON_*` codes `claim_state.lapsed` carries;
- the newly-added `REASON_CLAIM_B_LAPSED` renders real copy (before, the
  template's `claim_b_lapsed` branch referenced a reason absent from the
  closed vocab);
- an unknown lapsed code degrades to the fallback, never a raw code or crash.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader
from selectolax.parser import HTMLParser

from src.domain.logic import capabilities


def _render(*, a=False, b=frozenset(), lapsed=()) -> str:
    domain_templates = Path(__file__).resolve().parents[1]  # src/domain/templates
    env = Environment(loader=FileSystemLoader(str(domain_templates)))
    env.globals["capabilities"] = capabilities
    claim_state = SimpleNamespace(a=a, b=b, lapsed=tuple(lapsed))
    return env.get_template("profile/_reverify.html").render(claim_state=claim_state)


def test_reverify_lapsed_card_reads_entirely_from_reason_meta() -> None:
    meta = capabilities.reason_meta(capabilities.REASON_CLAIM_A_LAPSED)
    tree = HTMLParser(_render(lapsed=[capabilities.REASON_CLAIM_A_LAPSED]))
    card = tree.css_first("article.step-card--error")
    assert card is not None
    assert card.css_first("strong").text(strip=True) == meta.title
    assert meta.unlock in card.text()
    fix = card.css_first("a[role='button']")
    assert fix.attributes.get("href") == meta.fix_url
    assert meta.fix_label in fix.text()
    # The raw reason code never leaks into the rendered card.
    assert "claim_a_lapsed" not in card.text()


def test_reverify_renders_newly_added_claim_b_lapsed() -> None:
    """Pins the vocab-gap fix: before `REASON_CLAIM_B_LAPSED` existed, the
    template's `claim_b_lapsed` branch named a reason absent from the closed
    vocab. It now resolves to real copy via `reason_meta`."""
    tree = HTMLParser(_render(lapsed=[capabilities.REASON_CLAIM_B_LAPSED]))
    card = tree.css_first("article.step-card--error")
    assert card.css_first("strong").text(strip=True) == "Organization representation"
    assert "Re-verify authority" in card.css_first("a[role='button']").text()


def test_reverify_unknown_lapsed_reason_falls_back_not_raises() -> None:
    fallback = capabilities.reason_meta("totally-not-a-reason")
    tree = HTMLParser(_render(lapsed=["totally-not-a-reason"]))
    card = tree.css_first("article.step-card--error")
    assert card.css_first("strong").text(strip=True) == fallback.title
    assert card.css_first("a[role='button']").attributes.get("href") == "/profile"


def test_reverify_still_active_card_lists_unlapsed_claims() -> None:
    """The 'Still active' card keys its membership checks off the REASON_*
    constants (not loose string literals), so it can't drift from the vocab."""
    from uuid import uuid4

    html = _render(a=True, b=frozenset({uuid4()}), lapsed=())
    assert "Clinician identity — verified" in html
    assert "Organization representation — 1 organization(s)" in html
