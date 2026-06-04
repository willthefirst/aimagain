"""Tests for the ``picker`` macro in ``_shared/_picker.html``.

The picker is the shared "choose your path" lego piece behind both picker
species in the resource grammar (see
``src/domain/routes/RESOURCE_GRAMMAR.md`` § "Pickers — two species, one
component"). The two species differ *only* in where each card's ``href``
points — within the resource (discriminator: ``/posts/form?kind=…``) or out
to another resource's form (dispatching: ``/clinicians/form``). These tests
pin that the macro is href-agnostic (same markup for both), renders one
card per option in order, and renders a ``selected`` option as a
non-clickable marked card rather than a link.
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


def test_picker_renders_one_link_card_per_option_in_order() -> None:
    """Each non-selected option becomes an `<a class="picker-option">` card
    carrying the option's `href`, an `<h2>` heading, and a `<p>`
    description — in the order supplied."""
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

    cards = tree.css("a.picker-option")
    assert len(cards) == 2
    assert [c.attributes.get("href") for c in cards] == [
        "/posts/form?kind=referral",
        "/posts/form?kind=clinician_opening",
    ]
    assert [c.css_first("h2").text(strip=True) for c in cards] == [
        "Referral",
        "Clinician",
    ]
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

    cards = tree.css("a.picker-option")
    assert len(cards) == 2
    # Cross-resource hrefs render through unchanged — same card shape as the
    # discriminator species, no special-casing.
    assert {c.attributes.get("href") for c in cards} == {
        "/clinicians/form",
        "/organizations/form",
    }
    # No "selected" marker species leaks in for a plain option list.
    assert tree.css_first(".picker-option--selected") is None


def test_picker_selected_option_renders_marked_card_not_a_link() -> None:
    """A `selected=True` option renders a non-clickable
    `.picker-option--selected` card (a `<div>`, no `href`) carrying a
    checkmark glyph — so an active path can't be re-selected. Other options
    stay as link cards."""
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

    selected = tree.css_first("div.picker-option--selected")
    assert selected is not None
    # Selected card is not a link and carries no navigation target.
    assert selected.tag == "div"
    assert selected.css_first("i.icon-check") is not None
    assert selected.css_first("h2").text(strip=True).endswith("Path A")
    # The non-selected sibling is still a real link card.
    links = tree.css("a.picker-option")
    assert len(links) == 1
    assert links[0].attributes.get("href") == "/x/form?kind=b"


def test_picker_empty_options_renders_empty_grid() -> None:
    """An empty option list renders the `.picker` grid wrapper with no
    cards — no crash, no stray markup."""
    env = _make_env()
    tree = HTMLParser(_render_picker(env, []))
    grid = tree.css_first("div.picker")
    assert grid is not None
    assert grid.css("a.picker-option") == []
