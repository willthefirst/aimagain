"""Tests for the ``filter_field`` macro in ``_shared/_filter_field.html``.

The macro renders one declared ``Filter`` spec object as an inline form
control, shared by the browse sidebar (``views/list.html``) and the
full-page search (``views/search.html``). These tests pin the one piece of
behaviour the two surfaces differ on: the ``heading`` flag.

The full-page search renders each field's own section heading (text label
for text/select controls, ``<legend>`` for multi/radio fieldsets). The
browse sidebar wraps each field in a Pico accordion whose ``<summary>``
already supplies the heading, so it calls the macro with ``heading=false``
to suppress the now-redundant inline heading — the flag checkbox's inline
label is the control itself, not a section heading, so it always renders.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(f: SimpleNamespace, value: object, *, heading: bool) -> str:
    env = _make_env()
    template = (
        '{%- from "_shared/_filter_field.html" import filter_field -%}'
        "{{ filter_field(f, value, heading=heading) }}"
    )
    return env.from_string(template).render(f=f, value=value, heading=heading)


def _multi_choice() -> SimpleNamespace:
    return SimpleNamespace(
        kind="choice",
        name="license_type",
        display_label="License type",
        multi=True,
        radio=False,
        choices=(("psyd", "PsyD"), ("lcsw", "LCSW")),
    )


def _text() -> SimpleNamespace:
    return SimpleNamespace(
        kind="text",
        name="keyword",
        display_label="Keyword",
        placeholder="Search…",
    )


def test_multi_choice_renders_legend_when_heading_true() -> None:
    """Full-page search keeps each multi-choice field's `<legend>` so the
    section is self-describing without an enclosing accordion."""
    tree = HTMLParser(_render(_multi_choice(), [], heading=True))
    legend = tree.css_first("fieldset.search-checkbox-fieldset legend")
    assert legend is not None
    assert legend.text(strip=True) == "License type"


def test_multi_choice_omits_legend_when_heading_false() -> None:
    """In the sidebar accordion the `<summary>` carries the heading, so the
    macro suppresses the `<legend>` to avoid duplicating the title — but the
    fieldset and its checkboxes still render."""
    tree = HTMLParser(_render(_multi_choice(), [], heading=False))
    fieldset = tree.css_first("fieldset.search-checkbox-fieldset")
    assert fieldset is not None, "fieldset must still render with heading=false"
    assert fieldset.css_first("legend") is None
    boxes = fieldset.css('input[type="checkbox"][name="license_type"]')
    assert len(boxes) == 2, "every choice still renders a checkbox"


def test_text_omits_inline_label_text_when_heading_false() -> None:
    """The text filter's inline `display_label` is suppressed with
    heading=false (the accordion summary supplies it), but the `<input>`
    and its placeholder remain."""
    with_heading = _render(_text(), None, heading=True)
    assert "Keyword" in with_heading
    tree = HTMLParser(_render(_text(), None, heading=False))
    assert "Keyword" not in tree.body.text()
    field = tree.css_first('input[type="search"][name="keyword"]')
    assert field is not None
    assert field.attributes.get("placeholder") == "Search…"
