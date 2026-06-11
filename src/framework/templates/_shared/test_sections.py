"""Tests for the section-shape macros in ``_shared/sections.html``.

``fact`` + ``facts_block`` are the canonical pair for rendering a
labeled key/value rows panel — used by every list-card body, every
detail-page card body, and a few form-page confirmation surfaces.
Domain templates must compose these macros instead of hand-rolling
the ``<section class="entity-facts"><dl>…</dl></section>`` chrome
(per #1193's component-library rule).
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


def _render(env: Environment, body: str) -> str:
    template = (
        '{%- from "_shared/sections.html" import fact, facts_block -%}'
        "{% call facts_block() %}" + body + "{% endcall %}"
    )
    return env.from_string(template).render()


def test_facts_block_emits_canonical_section_and_dl_wrapper() -> None:
    """The wrapper is a single ``<section class="entity-facts">``
    containing a single ``<dl>``. Domain templates rely on the
    ``.entity-facts`` class for Pico styling and the grid layout."""
    env = _make_env()
    html = _render(env, "{{ fact('npi', 'NPI', '1234567890') }}")
    tree = HTMLParser(html)
    sections = tree.css("section.entity-facts")
    assert len(sections) == 1, "Expected one <section class='entity-facts'>"
    dls = sections[0].css("dl")
    assert len(dls) == 1, "Expected one <dl> directly inside the section"


def test_facts_block_renders_caller_rows_inside_the_dl() -> None:
    """Caller-supplied ``fact(...)`` rows render as ``<div data-fact>``
    wrappers inside the ``<dl>``, in caller-supplied order."""
    env = _make_env()
    html = _render(
        env,
        "{{ fact('npi', 'NPI', '1234567890') }}"
        "{{ fact('state', 'State served', 'NY') }}",
    )
    tree = HTMLParser(html)
    rows = tree.css("section.entity-facts > dl > div[data-fact]")
    assert [r.attributes.get("data-fact") for r in rows] == ["npi", "state"]


def test_facts_block_empty_body_still_emits_wrapper() -> None:
    """An empty caller body still emits the wrapper chrome — relevant
    for templates that gate every row behind an ``{% if %}`` and the
    gate happens to be false at render time. (The wrapper is cheap; a
    missing wrapper would break the surrounding card layout.)"""
    env = _make_env()
    html = _render(env, "")
    tree = HTMLParser(html)
    assert tree.css_first("section.entity-facts dl") is not None
    assert tree.css_first("section.entity-facts dl div[data-fact]") is None
