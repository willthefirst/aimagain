"""Tests for `_shared/_provider_ref.html`.

`provider_ref(ref, redacted, linked)` is the single home for the
"<name> · <org>" denotation the post detail card (linked) and the feed
row (unlinked) both render. These pin the cases — linked clinician/program
+ org, sole-prop (no org), name-only (no entity), redacted, and the
`linked=False` plain-text variant — plus the CSS-driven middot (no
literal `·` in the markup).
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from src.framework.templates._test_env import make_test_env

_TEMPLATE = (
    '{%- from "_shared/_provider_ref.html" import provider_ref -%}'
    "{{ provider_ref(ref, redacted=redacted, linked=linked) }}"
)


def _render(ref, *, redacted=False, linked=True) -> HTMLParser:
    env = make_test_env()
    return HTMLParser(
        env.from_string(_TEMPLATE).render(ref=ref, redacted=redacted, linked=linked)
    )


def test_clinician_with_org_links_both_parts() -> None:
    tree = _render(
        {
            "name": "Jane Smith",
            "entity": "clinician",
            "id": "c1",
            "org": {"id": "o1", "name": "Acme Counseling"},
        }
    )
    name_link = tree.css_first("a[href='/clinicians/c1']")
    org_link = tree.css_first("a[href='/organizations/o1']")
    assert name_link is not None and name_link.text() == "Jane Smith"
    assert org_link is not None and org_link.text() == "Acme Counseling"
    # The middot comes from the `.meta` CSS rule, never a literal char.
    assert "·" not in (tree.body.text() or "")
    assert tree.css_first("span.meta") is not None


def test_program_links_to_program_detail() -> None:
    tree = _render(
        {
            "name": "RISE IOP",
            "entity": "program",
            "id": "p1",
            "org": {"id": "o1", "name": "Acme Health"},
        }
    )
    assert tree.css_first("a[href='/programs/p1']") is not None
    assert tree.css_first("a[href='/organizations/o1']") is not None


def test_sole_prop_clinician_renders_name_only() -> None:
    tree = _render(
        {"name": "Jane Smith", "entity": "clinician", "id": "c1", "org": None}
    )
    assert tree.css_first("a[href='/clinicians/c1']") is not None
    assert tree.css_first("a[href^='/organizations/']") is None


def test_name_only_reference_renders_plain_text_no_anchor() -> None:
    tree = _render({"name": "Carlos Rivera", "entity": None, "id": None, "org": None})
    assert tree.css("a") == []
    assert "Carlos Rivera" in (tree.body.text() or "")


def test_linked_false_renders_name_and_org_as_plain_text() -> None:
    """The feed row passes `linked=False`: same "<name> · <org>" text, but
    no anchors to the author or their org."""
    tree = _render(
        {
            "name": "Jane Smith",
            "entity": "clinician",
            "id": "c1",
            "org": {"id": "o1", "name": "Acme Counseling"},
        },
        linked=False,
    )
    assert tree.css("a") == []
    body_text = tree.body.text() or ""
    assert "Jane Smith" in body_text
    assert "Acme Counseling" in body_text
    # Still the meta_list wrapper, so the CSS middot still joins the parts.
    assert tree.css_first("span.meta") is not None
    assert "·" not in body_text


def test_redacted_withholds_name_and_org_behind_locks() -> None:
    tree = _render(
        {
            "name": "Jane Smith",
            "entity": "clinician",
            "id": "c1",
            "org": {"id": "o1", "name": "Acme Counseling"},
        },
        redacted=True,
    )
    # No real links or names leak.
    assert tree.css("a[href^='/clinicians/']") == []
    assert tree.css("a[href^='/organizations/']") == []
    assert "Jane Smith" not in (tree.body.text() or "")
    assert "Acme Counseling" not in (tree.body.text() or "")
    # Two locked placeholders (clinician + org).
    assert len(tree.css("button.locked-ghost-btn")) == 2


def test_empty_reference_renders_nothing() -> None:
    assert _render(None).css("span.meta") == []
    assert (
        _render({"name": None, "entity": None, "id": None, "org": None}).css(
            "span.meta"
        )
        == []
    )
