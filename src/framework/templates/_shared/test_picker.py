"""Tests for the ``picker`` macro in ``_shared/_picker.html``.

The picker is the shared "choose your path" lego piece behind both picker
species in the resource grammar (see
``src/domain/routes/RESOURCE_GRAMMAR.md`` § "Pickers — two species, one
component"). The two species differ *only* in where each card's ``href``
points — within the resource (discriminator: ``/posts/form?kind=…``) or out
to another resource's form (dispatching: ``/clinicians/form``). These tests
pin that the macro is href-agnostic (same markup for both), renders one
``<article class="picker-option">`` card per option in order, and renders a
``selected`` option as a non-clickable card tagged ``aria-current="page"``
rather than a link.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render_picker(env: Environment, options: list[dict]) -> str:
    template = '{%- from "_shared/_picker.html" import picker -%}{{ picker(options) }}'
    return env.from_string(template).render(options=options)


def test_picker_renders_one_article_card_per_option_in_order() -> None:
    """Each non-selected option becomes an ``<article class="picker-option">``
    card whose top-level ``<h2><a>`` carries the option's ``href`` and
    heading text, with the description as a plain ``<p>`` — in the order
    supplied. No ``<header>`` wrapping after #1330."""
    env = _make_env()
    options = [
        {
            "href": "/posts/form?kind=referral",
            "heading": "Referral",
            "description": "Place a client.",
        },
        {
            "href": "/posts/form?kind=clinician_opening",
            "heading": "Clinician",
            "description": "Open caseload.",
        },
    ]
    tree = HTMLParser(_render_picker(env, options))

    cards = tree.css("article.picker-option")
    assert len(cards) == 2
    headings = [c.css_first("h2 a") for c in cards]
    assert [h.attributes.get("href") for h in headings] == [
        "/posts/form?kind=referral",
        "/posts/form?kind=clinician_opening",
    ]
    assert [h.text(strip=True) for h in headings] == ["Referral", "Clinician"]
    assert cards[0].css_first("p").text(strip=True) == "Place a client."


def test_picker_is_href_agnostic_across_both_species() -> None:
    """The dispatching species (cross-resource hrefs pointing at *other*
    resources' forms) renders identical markup to the discriminator species
    — the macro only ever consumes `href`, so self- vs cross-resource is
    the caller's business, not the component's."""
    env = _make_env()
    dispatching = [
        {
            "href": "/clinicians/form",
            "heading": "I'm a clinician",
            "description": "Verify your NPI.",
        },
        {
            "href": "/organizations/form",
            "heading": "I represent an org",
            "description": "Register it.",
        },
    ]
    tree = HTMLParser(_render_picker(env, dispatching))

    cards = tree.css("article.picker-option")
    assert len(cards) == 2
    # Cross-resource hrefs render through unchanged — same card shape as the
    # discriminator species, no special-casing.
    hrefs = {c.css_first("h2 a").attributes.get("href") for c in cards}
    assert hrefs == {"/clinicians/form", "/organizations/form"}
    # No "selected" marker species leaks in for a plain option list.
    assert tree.css_first("article.picker-option[aria-current]") is None


def test_picker_selected_option_renders_marked_card_not_a_link() -> None:
    """A ``selected=True`` option renders an ``article.picker-option`` tagged
    ``aria-current="page"`` whose heading is plain text (no nested ``<a>``)
    and carries a checkmark glyph — so an active path can't be re-selected.
    Other options stay as link cards."""
    env = _make_env()
    options = [
        {
            "href": "/x/form?kind=a",
            "heading": "Path A",
            "description": "First.",
            "selected": True,
        },
        {"href": "/x/form?kind=b", "heading": "Path B", "description": "Second."},
    ]
    tree = HTMLParser(_render_picker(env, options))

    selected = tree.css_first("article.picker-option[aria-current]")
    assert selected is not None
    assert selected.attributes.get("aria-current") == "page"
    # Selected card is not a link — its heading is plain text, no nested <a>.
    assert selected.css_first("h2 a") is None
    assert selected.css_first("i.icon-check") is not None
    assert selected.css_first("h2").text(strip=True).endswith("Path A")
    # The non-selected sibling is still a real link card.
    links = tree.css("article.picker-option:not([aria-current]) h2 a")
    assert len(links) == 1
    assert links[0].attributes.get("href") == "/x/form?kind=b"


def test_picker_locked_option_renders_locked_link_with_reason() -> None:
    """A ``locked_reason`` option renders the heading as a `data-locked-cta`
    anchor (no `href`) with the lock glyph, so the locked-affordance JS
    in base.html can anchor its popover. Other options stay as normal
    link cards — the locked branch is per-option, not per-picker."""
    env = _make_env()
    options = [
        {
            "href": "/posts/form?kind=referral",
            "heading": "Referral",
            "description": "Place a client.",
        },
        {
            "href": "/posts/form?kind=program_intake",
            "heading": "Program intake",
            "description": "Announce open slots.",
            "locked_reason": "program_intake_locked",
        },
    ]
    tree = HTMLParser(_render_picker(env, options))

    cards = tree.css("article.picker-option")
    assert len(cards) == 2
    # First tile is a normal link card.
    first_link = cards[0].css_first("h2 a")
    assert first_link.attributes.get("href") == "/posts/form?kind=referral"
    assert first_link.attributes.get("data-locked-cta") is None
    # Locked tile renders a locked-link anchor with the reason code and no
    # navigable href — clicking opens the popover instead of landing on
    # the form.
    locked = cards[1].css_first("h2 a")
    assert locked.attributes.get("data-locked-cta") == "program_intake_locked"
    assert locked.attributes.get("href") is None
    assert locked.attributes.get("aria-disabled") == "true"
    assert "locked-link" in locked.attributes.get("class", "")
    assert cards[1].css_first("h2 i.icon-lock") is not None
    # The description still renders so the user sees what the tile is for.
    assert cards[1].css_first("p").text(strip=True) == "Announce open slots."


def test_picker_empty_options_renders_nothing() -> None:
    """An empty option list renders no cards — the macro stacks vanilla
    ``<article>`` blocks, so with zero options it emits nothing for the
    layout engine to render."""
    env = _make_env()
    tree = HTMLParser(_render_picker(env, []))
    assert tree.css("article.picker-option") == []
