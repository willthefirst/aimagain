"""Tests for the form-field render macros in ``_shared/form_fields.html``.

Each macro renders a labelled control with Pico-canonical structure:

  <label>
    <text>
    <input | select | textarea>
    <small id="<name>-helper">          ← optional, present when help= passed
  </label>

These tests pin that contract so future edits don't silently regress the
shape (helper text drifting outside the label is exactly the bug class
that motivated the rewrite).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    """Jinja env that resolves ``_shared/form_fields.html`` from the
    framework templates root, with per-test stubs in a DictLoader.

    Mirrors the runtime two-root loader in
    ``src.framework.rendering.templating``; per-template tests pin
    runtime behavior without needing a full app boot.
    """
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(env: Environment, body: str) -> str:
    """Render an inline template body that imports from the macro file.

    The body should not include the import line — this helper prepends
    it so tests can stay focused on the macro call under test.
    """
    template = textwrap.dedent(f"""\
        {{%- from "_shared/form_fields.html" import text_field, textarea_field, url_field, select_field, multi_select_field, entity_select_field, radio_bool_field -%}}
        {body}
        """)
    return env.from_string(template).render()


# --- text_field -----------------------------------------------------------


def test_text_field_renders_label_wrapping_input_no_helper() -> None:
    """Default: label wraps text + input, no `<small>`, no
    aria-describedby."""
    html = _render(_make_env(), '{{ text_field("zip", "ZIP") }}')
    tree = HTMLParser(html)
    label = tree.css_first('label[for="zip"]')
    assert label is not None
    inp = label.css_first('input[type="text"][name="zip"]')
    assert inp is not None
    # selectolax sets bool-attr value to `None`; presence in keys is the
    # real signal. `assert attr.get(...)` would false-negative.
    assert "required" in inp.attributes
    assert "aria-describedby" not in inp.attributes
    assert label.css_first("small") is None


def test_text_field_with_help_emits_small_inside_label_linked_via_aria() -> None:
    """`help=` renders a `<small id="<name>-helper">` *inside* the
    `<label>` after the input, and the input carries
    `aria-describedby` pointing at it."""
    html = _render(
        _make_env(),
        '{{ text_field("npi", "NPI", help="10-digit National Provider Identifier. Optional.") }}',
    )
    tree = HTMLParser(html)
    label = tree.css_first('label[for="npi"]')
    assert label is not None
    inp = label.css_first('input[name="npi"]')
    assert inp.attributes.get("aria-describedby") == "npi-helper"
    small = label.css_first("small#npi-helper")
    assert small is not None
    assert "10-digit National Provider Identifier" in small.text()
    # Small is a child of the label, not a sibling.
    assert tree.css_first('label[for="npi"] > small#npi-helper') is not None


def test_text_field_help_is_emitted_as_safe_so_inline_links_render() -> None:
    """`help=` is HTML-safe by design so helper text can carry an inline
    link (e.g. "Don't see your org? Create one first."). Inline scripts
    or untrusted strings are the caller's problem to escape."""
    html = _render(
        _make_env(),
        '{{ text_field("name", "Name", help=\'See <a href="/help">docs</a>.\') }}',
    )
    tree = HTMLParser(html)
    small = tree.css_first("small#name-helper")
    assert small.css_first('a[href="/help"]') is not None


def test_text_field_invalid_true_sets_aria_invalid_true() -> None:
    """`invalid=true` → `aria-invalid="true"`; Pico colors the input +
    small red. `invalid=false` → `aria-invalid="false"` (valid state).
    `invalid=none` (default) → no aria-invalid at all."""
    html_true = _render(_make_env(), '{{ text_field("x", "X", invalid=true) }}')
    html_false = _render(_make_env(), '{{ text_field("x", "X", invalid=false) }}')
    html_none = _render(_make_env(), '{{ text_field("x", "X") }}')
    assert (
        HTMLParser(html_true).css_first("input").attributes.get("aria-invalid")
        == "true"
    )
    assert (
        HTMLParser(html_false).css_first("input").attributes.get("aria-invalid")
        == "false"
    )
    assert "aria-invalid" not in HTMLParser(html_none).css_first("input").attributes


def test_text_field_type_parameter_overrides_default() -> None:
    """`type=` defaults to `text` and threads through (`date`, `url`,
    etc.). Pico styles all standard HTML5 input types out of the box."""
    html = _render(_make_env(), '{{ text_field("d", "D", type="date") }}')
    assert HTMLParser(html).css_first("input").attributes.get("type") == "date"


# --- textarea_field -------------------------------------------------------


def test_textarea_field_with_help_emits_small_inside_label() -> None:
    html = _render(
        _make_env(),
        '{{ textarea_field("desc", "Description", help="No PII.") }}',
    )
    tree = HTMLParser(html)
    label = tree.css_first('label[for="desc"]')
    ta = label.css_first("textarea")
    assert ta.attributes.get("aria-describedby") == "desc-helper"
    assert label.css_first("small#desc-helper") is not None


# --- url_field ------------------------------------------------------------


def test_url_field_is_text_field_with_type_url() -> None:
    """`url_field` is sugar for `text_field(type="url")` — the actual
    delegation lives in the macro definition. Test confirms the
    rendered shape and the help-text plumbing both work through the
    thin wrapper."""
    html = _render(
        _make_env(),
        '{{ url_field("site", "Website", help="https://...") }}',
    )
    tree = HTMLParser(html)
    inp = tree.css_first('input[name="site"]')
    assert inp.attributes.get("type") == "url"
    assert inp.attributes.get("aria-describedby") == "site-helper"


# --- select_field ---------------------------------------------------------


def test_select_field_with_help_emits_small_inside_label() -> None:
    html = _render(
        _make_env(),
        '{{ select_field("kind", "Kind", ("a", "b"), help="Pick one.") }}',
    )
    tree = HTMLParser(html)
    label = tree.css_first('label[for="kind"]')
    sel = label.css_first("select")
    assert sel.attributes.get("aria-describedby") == "kind-helper"
    small = label.css_first("small#kind-helper")
    assert small is not None and "Pick one." in small.text()


def test_select_field_placeholder_emits_disabled_option_when_no_current() -> None:
    """`placeholder=true` + `current=None` renders the disabled-selected
    `--` option Pico uses to convey "no value yet". When `current` is
    set, the placeholder is suppressed so the value is the visible
    selection."""
    html = _render(
        _make_env(),
        '{{ select_field("kind", "Kind", ("a", "b"), placeholder=true) }}',
    )
    tree = HTMLParser(html)
    placeholder = tree.css_first("option[disabled][selected]")
    assert placeholder is not None
    assert placeholder.text().strip() == "--"


# --- multi_select_field ---------------------------------------------------


def test_multi_select_field_with_help_links_each_via_aria() -> None:
    """`<select multiple>` carries `aria-describedby` on the select
    itself; the `<small>` lives inside the label after the select."""
    html = _render(
        _make_env(),
        '{{ multi_select_field("tags", "Tags", ("a", "b"), help="Pick any.") }}',
    )
    tree = HTMLParser(html)
    sel = tree.css_first('select[name="tags"][multiple]')
    assert sel.attributes.get("aria-describedby") == "tags-helper"
    assert tree.css_first("small#tags-helper") is not None


# --- entity_select_field --------------------------------------------------


class _Stub:
    """Tiny stand-in for a domain entity that the macro can read
    `.id`/`.name` from. Mirrors the shape of an SQLAlchemy ORM row that
    the macro accepts at runtime."""

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


def test_entity_select_field_renders_option_per_entity() -> None:
    env = _make_env()
    env.globals["entities"] = [_Stub("1", "Alpha"), _Stub("2", "Bravo")]
    html = env.from_string(
        '{%- from "_shared/form_fields.html" import entity_select_field -%}'
        '{{ entity_select_field("org_id", "Organization", entities) }}'
    ).render()
    tree = HTMLParser(html)
    sel = tree.css_first('select[name="org_id"]')
    opts = sel.css("option")
    # Placeholder + 2 entities = 3 options total.
    assert len(opts) == 3
    assert opts[1].text().strip() == "Alpha"
    assert opts[2].text().strip() == "Bravo"


def test_entity_select_field_blank_label_emits_enabled_empty_option() -> None:
    """`blank_label="..."` adds an enabled `<option value="">` instead
    of the disabled `--` placeholder. Used for "(root — no parent)" on
    the Org parent picker — the empty value is a real selection, not a
    "you must pick something" prompt."""
    env = _make_env()
    env.globals["entities"] = []
    html = env.from_string(
        '{%- from "_shared/form_fields.html" import entity_select_field -%}'
        '{{ entity_select_field("parent_org_id", "Parent organization", entities, blank_label="(root — no parent)", required=false) }}'
    ).render()
    tree = HTMLParser(html)
    # selectolax's CSS-`>` (direct-child combinator) is fussy; query
    # for the option without the combinator and confirm parent is the
    # right select.
    options = tree.css('select[name="parent_org_id"] option')
    # selectolax surfaces empty-string attribute values as `None`, so an
    # `<option value="">` shows up with `attributes["value"] is None`.
    # Use key-presence + falsy-value match.
    root = next(
        (o for o in options if "value" in o.attributes and not o.attributes["value"]),
        None,
    )
    assert root is not None, f"rendered html: {html!r}"
    assert "(root" in root.text()
    # `disabled` is a bool-attr: absent from `attributes` keys when not
    # set. selectolax surfaces value=None for present-but-valueless
    # attrs, which `.get()` flattens to the same None — check key
    # membership explicitly.
    assert "disabled" not in root.attributes


def test_entity_select_field_preselects_current() -> None:
    env = _make_env()
    env.globals["entities"] = [_Stub("1", "Alpha"), _Stub("2", "Bravo")]
    html = env.from_string(
        '{%- from "_shared/form_fields.html" import entity_select_field -%}'
        '{{ entity_select_field("org_id", "Organization", entities, current="2") }}'
    ).render()
    tree = HTMLParser(html)
    selected = tree.css_first('select[name="org_id"] option[selected]')
    assert selected is not None
    assert selected.attributes.get("value") == "2"


# --- optional indicator ---------------------------------------------------


def test_optional_marker_has_no_literal_space_before_small() -> None:
    """Spacing between the label text and the `(optional)` marker is
    owned by `.form-field-optional { margin-inline-start }` in
    `base.html` — the macro must not emit a literal space character
    before `<small class="form-field-optional">`. Whitespace-as-spacing
    in markup is the anti-pattern this test pins against regression.
    """
    html = _render(_make_env(), '{{ text_field("zip", "ZIP", required=false) }}')
    # The label text and the `<small>` must be flush in the rendered
    # source — no run of one-or-more whitespace chars between them.
    assert "ZIP<small" in html, (
        "Expected label text flush against `<small>` (CSS owns the "
        f"gap). Rendered HTML: {html!r}"
    )


def test_optional_marker_renders_inside_form_field_label_span() -> None:
    """Sanity-check the structural contract while we're here: when
    `required=false`, the `<small class="form-field-optional">` lives
    inside the `<span class="form-field-label">` next to the label
    text. This is what lets the CSS rule key off `.form-field-optional`
    without any additional selector specificity."""
    html = _render(_make_env(), '{{ text_field("zip", "ZIP", required=false) }}')
    tree = HTMLParser(html)
    span = tree.css_first("span.form-field-label")
    assert span is not None
    small = span.css_first("small.form-field-optional")
    assert small is not None
    assert small.text().strip() == "(optional)"


# --- radio_bool_field -----------------------------------------------------


def test_radio_bool_field_with_help_emits_small_inside_fieldset() -> None:
    """The bool radios are wrapped in `<fieldset>`+`<legend>` because
    one logical question owns two controls. Helper text becomes a
    `<small id="<name>-helper">` child of the `<fieldset>` (after the
    radios), and *each* radio carries `aria-describedby` so SRs hear
    the helper on either selection."""
    html = _render(
        _make_env(),
        '{{ radio_bool_field("ok", "OK?", help="Pick one.") }}',
    )
    tree = HTMLParser(html)
    fs = tree.css_first("fieldset")
    radios = fs.css('input[type="radio"]')
    assert len(radios) == 2
    for r in radios:
        assert r.attributes.get("aria-describedby") == "ok-helper"
    assert fs.css_first("small#ok-helper") is not None


# --- repository-level guard ------------------------------------------------


@pytest.mark.parametrize(
    "form_template",
    [
        # Every form-shaped template under domain/. Add new form
        # templates here so the orphan-small check runs against them.
        "src/domain/templates/posts/openings/_form_clinician_opening.html",
        "src/domain/templates/posts/openings/_form_program_intake.html",
        "src/domain/templates/posts/referrals/_form.html",
        "src/domain/templates/organizations/form_new.html",
        "src/domain/templates/organizations/form_edit.html",
        "src/domain/templates/providers/form_new.html",
        "src/domain/templates/providers/form_edit.html",
        "src/domain/templates/programs/form_new.html",
        "src/domain/templates/programs/form_edit.html",
    ],
)
def test_no_orphan_small_next_to_macro_call(form_template: str) -> None:
    """Lints the template source: a `<small>` should never appear at
    the same indentation as a macro call `{{ ... }}`. The legitimate
    cases are `<small>` *inside* a `<fieldset>` after multiple inputs
    in a `<div class="grid">` (fieldset-scoped helper) — those have a
    `</div>` or `</fieldset>` line between the macro and the small, so
    the simple adjacency rule below catches the bad pattern without
    flagging the good one.

    Pinned by the form-fields refactor that introduced `help=` (this
    file's docstring at the top of `_shared/form_fields.html` documents
    the rule).
    """
    # parents[4] = repo root (this file is at
    # src/framework/templates/_shared/test_form_fields.py).
    text = (Path(__file__).resolve().parents[4] / form_template).read_text()
    lines = text.splitlines()
    offenders: list[tuple[int, str]] = []
    for i in range(1, len(lines)):
        prev = lines[i - 1].rstrip()
        curr = lines[i].lstrip()
        # Adjacent: previous line ends with `}}` (Jinja macro call),
        # current line begins with `<small`. That's the bug shape.
        if prev.endswith("}}") and curr.startswith("<small"):
            offenders.append((i + 1, lines[i]))
    assert not offenders, (
        f"Orphan <small> next to a macro call in {form_template}:\n"
        + "\n".join(f"  line {ln}: {body}" for ln, body in offenders)
        + "\nUse the macro's `help=` parameter instead — see "
        "src/framework/templates/_shared/form_fields.html docstring."
    )
