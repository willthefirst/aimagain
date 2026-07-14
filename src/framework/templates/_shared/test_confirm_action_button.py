"""Tests for the ``confirm_action_button`` macro in ``_shared/actions.html``.

``confirm_action_button`` is the generic non-delete state-change button
(PUT/POST + ``hx-confirm`` + optional JSON-encoded ``hx-vals``). It's
the cousin of ``confirm_delete_button``; three sites use it today —
the two activation buttons in ``users/_admin_actions.html`` and the
Attest-active button in ``clinician_credentials/licensures/_form_licensure.html``.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(str(Path(__file__).resolve().parents[1]))
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(env: Environment, args: str) -> str:
    template = (
        '{%- from "_shared/actions.html" import confirm_action_button -%}'
        "{{ confirm_action_button(" + args + ") }}"
    )
    return env.from_string(template).render()


def test_put_emits_hx_put_with_confirm_and_label() -> None:
    """The PUT branch emits the expected `<button>` with `hx-put`,
    `hx-confirm`, and the supplied label as text."""
    env = _make_env()
    html = _render(
        env,
        "'put', '/users/abc/activation', 'Deactivate user?', 'Deactivate'",
    )
    button = HTMLParser(html).css_first("button")
    assert button is not None
    assert button.attributes.get("hx-put") == "/users/abc/activation"
    assert button.attributes.get("hx-confirm") == "Deactivate user?"
    assert button.text().strip() == "Deactivate"
    assert "secondary outline" in (button.attributes.get("class") or "")


def test_post_emits_hx_post_not_hx_put() -> None:
    """The POST branch emits `hx-post` and does NOT also emit `hx-put` —
    the action-direction invariant matches the one pinned in
    ``test_favorite_toggle``."""
    env = _make_env()
    html = _render(env, "'post', '/some/action', 'Confirm?', 'Do it'")
    button = HTMLParser(html).css_first("button")
    assert button.attributes.get("hx-post") == "/some/action"
    assert "hx-put" not in button.attributes


def test_hx_vals_lights_up_json_enc_and_payload() -> None:
    """When `hx_vals` is supplied, the macro also emits
    `hx-ext="json-enc"` (so the body lands as application/json — what
    the state-axis handlers expect) plus the literal JSON payload."""
    env = _make_env()
    html = _render(
        env,
        (
            "'put', '/users/abc/activation', 'Deactivate?', 'Deactivate', "
            'hx_vals=\'{"state": "deactivated"}\''
        ),
    )
    button = HTMLParser(html).css_first("button")
    assert button.attributes.get("hx-ext") == "json-enc"
    assert button.attributes.get("hx-vals") == '{"state": "deactivated"}'


def test_no_hx_vals_omits_hx_ext_and_hx_vals() -> None:
    """Default (no `hx_vals`) → no `hx-ext`, no `hx-vals`. The Attest
    site uses `hx_vals`; a hypothetical use site that doesn't need a
    body shouldn't get spurious `json-enc` either."""
    env = _make_env()
    html = _render(env, "'put', '/some/action', 'Confirm?', 'Do it'")
    button = HTMLParser(html).css_first("button")
    assert "hx-ext" not in button.attributes
    assert "hx-vals" not in button.attributes
