"""Tests for the ``favorite_toggle`` macro in ``_shared/actions.html``.

``favorite_toggle`` is the two-state toolbar Favorite / Unfavorite
button used on `/clinicians/{id}` and (eventually) any other detail
page that surfaces a per-target favorite affordance. The macro lives
at the framework level because the same toggle shape — different Pico
treatment per state, hx-confirm only on the destructive direction —
is what any future favorite-style affordance would want.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    """Construct a Jinja env with the framework root + a stub
    ``entity_url`` global so the macro can render in isolation."""
    stub = DictLoader({})
    framework = FileSystemLoader(str(Path(__file__).resolve().parents[1]))
    env = Environment(loader=ChoiceLoader([stub, framework]))

    def fake_entity_url(name: str, **kwargs: object) -> str:
        if name == "user_favorite":
            return f"/users/me/favorites/{kwargs['id']}"
        raise AssertionError(f"unexpected entity_url('{name}')")

    env.globals["entity_url"] = fake_entity_url
    return env


def _render(env: Environment, target_id: str, is_favorited: bool) -> str:
    template = (
        '{%- from "_shared/actions.html" import favorite_toggle -%}'
        "{{ favorite_toggle(target_id, is_favorited) }}"
    )
    return env.from_string(template).render(
        target_id=target_id, is_favorited=is_favorited
    )


def test_not_favorited_emits_favorite_post_button_in_li() -> None:
    """Unfavored state → a single `<li>` wrapping a `<button>` that POSTs
    to the user_favorite URL with `class="outline"` (primary CTA
    treatment) and no `hx-confirm` (the action is reversible)."""
    env = _make_env()
    html = _render(env, "clin-1", is_favorited=False)
    tree = HTMLParser(html)
    lis = tree.css("li")
    assert len(lis) == 1
    button = lis[0].css_first("button")
    assert button is not None
    assert button.text().strip() == "Favorite"
    assert button.attributes.get("hx-post") == "/users/me/favorites/clin-1"
    assert "outline" in (button.attributes.get("class") or "")
    assert "secondary" not in (button.attributes.get("class") or "")
    assert "hx-confirm" not in button.attributes


def test_favorited_emits_unfavorite_delete_button_with_confirm() -> None:
    """Favorited state → a single `<li>` wrapping a `<button>` that
    DELETEs the same URL with `class="secondary outline"` (muted) and
    an `hx-confirm` dialog (the action is irreversible from the user's
    perspective — losing the favorite means re-favoriting later)."""
    env = _make_env()
    html = _render(env, "clin-1", is_favorited=True)
    tree = HTMLParser(html)
    lis = tree.css("li")
    assert len(lis) == 1
    button = lis[0].css_first("button")
    assert button is not None
    assert button.text().strip() == "Unfavorite"
    assert button.attributes.get("hx-delete") == "/users/me/favorites/clin-1"
    klass = button.attributes.get("class") or ""
    assert "secondary" in klass and "outline" in klass
    assert button.attributes.get("hx-confirm") is not None
    assert "favorites" in button.attributes["hx-confirm"]


def test_post_button_has_no_delete_attr_and_vice_versa() -> None:
    """Pin the action-direction invariant: the un-favorited state must
    NOT also emit `hx-delete`, and the favorited state must NOT also
    emit `hx-post`. A failure here would mean both fire on one click."""
    env = _make_env()
    not_fav = HTMLParser(_render(env, "clin-1", is_favorited=False)).css_first("button")
    fav = HTMLParser(_render(env, "clin-1", is_favorited=True)).css_first("button")
    assert "hx-delete" not in not_fav.attributes
    assert "hx-post" not in fav.attributes
