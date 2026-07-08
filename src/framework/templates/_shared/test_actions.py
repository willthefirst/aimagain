"""Tests for the ``actions`` macro in ``_shared/actions.html``.

Covers the dirty-form cancel confirmation added in #703:
- The Cancel link carries ``data-cancel-btn`` so the inline script can
  find it via a stable selector.
- The ``<script>`` block is emitted in form layout (``wrapper="form"``)
  when a ``cancel_url`` is supplied.
- The script is *not* emitted in toolbar layout or when ``cancel_url``
  is absent.

JS behaviour (the confirm dialog itself) cannot be exercised in unit
tests; a browser (Playwright) test would be needed for full coverage.
The assertions here pin the HTML structure the JS depends on so a
refactor can't silently break the selector.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render_actions(env: Environment, **kwargs: object) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    template = textwrap.dedent(f"""\
        {{%- from "_shared/actions.html" import actions -%}}
        {{{{ actions({args}) }}}}
        """)
    return env.from_string(template).render()


# ---------------------------------------------------------------------------
# data-cancel-btn attribute
# ---------------------------------------------------------------------------


def test_cancel_link_carries_data_cancel_btn_in_form_layout() -> None:
    """Cancel link must expose ``data-cancel-btn`` so the inline script can
    bind a click listener to it without relying on class or text."""
    html = _render_actions(_make_env(), cancel_url="/things/1", submit_label="Save")
    tree = HTMLParser(html)
    cancel = tree.css_first("a[data-cancel-btn]")
    assert cancel is not None, "expected <a data-cancel-btn> in form layout"
    assert cancel.attributes.get("href") == "/things/1"


def test_cancel_renders_as_plain_muted_link_not_a_button() -> None:
    """Cancel uses Pico's native muted-link treatment: ``class="secondary"``
    with NO ``role="button"``, so it reads as a quiet text link beside the
    primary rather than competing as a second button (see the vocabulary
    table in ``_shared/actions.html``)."""
    html = _render_actions(_make_env(), cancel_url="/things/1", submit_label="Save")
    cancel = HTMLParser(html).css_first("a[data-cancel-btn]")
    assert cancel is not None
    classes = (cancel.attributes.get("class") or "").split()
    assert "secondary" in classes, "Cancel must carry Pico's `secondary` link class"
    assert (
        cancel.attributes.get("role") != "button"
    ), "Cancel must NOT be a `role=button` — it's a plain link, not a button"
    assert "outline" not in classes, "Cancel is no longer an outline button"


def test_cancel_link_carries_data_cancel_btn_in_toolbar_layout() -> None:
    """``data-cancel-btn`` is present in toolbar layout too — the attribute
    is on the element, not conditional on the wrapper."""
    html = _render_actions(_make_env(), cancel_url="/things/1", wrapper="toolbar")
    cancel = HTMLParser(html).css_first("a[data-cancel-btn]")
    assert cancel is not None


# ---------------------------------------------------------------------------
# <script> block presence / absence
# ---------------------------------------------------------------------------


def test_dirty_form_script_emitted_in_form_layout_with_cancel_url() -> None:
    """The inline script must be emitted when ``wrapper="form"`` (default)
    and a ``cancel_url`` is provided."""
    html = _render_actions(_make_env(), cancel_url="/things/1", submit_label="Save")
    tree = HTMLParser(html)
    script = tree.css_first("script")
    assert script is not None, "expected <script> block in form layout with cancel_url"
    text = script.text()
    assert "data-cancel-btn" in text, "<script> must reference data-cancel-btn selector"
    assert "Discard changes?" in text, "<script> must contain the confirm message"


def test_dirty_form_script_not_emitted_without_cancel_url() -> None:
    """No ``cancel_url`` → no script (nothing to guard against)."""
    html = _render_actions(_make_env(), submit_label="Save")
    assert HTMLParser(html).css_first("script") is None


def test_dirty_form_script_not_emitted_in_toolbar_layout() -> None:
    """In toolbar layout the script must be suppressed — the cancel link
    appears in a ``<menu>`` toolbar, not adjacent to a ``<form>``."""
    html = _render_actions(_make_env(), cancel_url="/things/1", wrapper="toolbar")
    assert HTMLParser(html).css_first("script") is None


# ---------------------------------------------------------------------------
# submit_label default — the "Save changes" canonical rule
# ---------------------------------------------------------------------------


def test_form_layout_submit_label_defaults_to_save_changes() -> None:
    """Per the domain templates README "every edit form uses Save changes,
    no exceptions" — the rule is encoded as the form-layout default here.
    Edit pages omit ``submit_label`` and inherit the canonical text;
    Create pages pass an explicit ``entity_create_label(...)``."""
    html = _render_actions(_make_env(), cancel_url="/things/1")
    button = HTMLParser(html).css_first("button[type='submit']")
    assert button is not None
    assert button.text().strip() == "Save changes"


def test_form_layout_explicit_submit_label_wins_over_default() -> None:
    """Create forms still pass an explicit label and must keep it —
    the default only fires when no label is supplied."""
    html = _render_actions(_make_env(), submit_label="Create organization")
    button = HTMLParser(html).css_first("button[type='submit']")
    assert button is not None
    assert button.text().strip() == "Create organization"


def test_toolbar_layout_submit_label_not_defaulted() -> None:
    """Detail-page toolbars never carry a Save button — omitting
    ``submit_label`` must NOT inject "Save changes" in toolbar layout."""
    html = _render_actions(_make_env(), wrapper="toolbar", edit_url="/things/1/form")
    assert HTMLParser(html).css_first("button[type='submit']") is None
