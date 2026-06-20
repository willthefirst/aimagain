"""Tests for `_shared/_affiliation_facts.html`.

`affiliation_facts(aff)` is the single home for rendering a
`ClinicianAffiliation`'s steady-state profile as `fact(...)` rows.
Every surface that shows the profile (the practices list card, post
surfaces) composes this macro, so these tests pin the row keys, the
label derivation, and the empty-suppression contract once for all of
them.
"""

from __future__ import annotations

from types import SimpleNamespace

from selectolax.parser import HTMLParser

from src.framework.templates._test_env import make_test_env

_TEMPLATE = (
    '{%- from "_shared/sections.html" import facts_block -%}'
    '{%- from "_shared/_affiliation_facts.html" import affiliation_facts -%}'
    "{% call facts_block() %}{{ affiliation_facts(aff) }}{% endcall %}"
)


def _render(aff) -> HTMLParser:
    env = make_test_env()
    return HTMLParser(env.from_string(_TEMPLATE).render(aff=aff))


def _full_aff() -> SimpleNamespace:
    return SimpleNamespace(
        in_person_sessions="yes",
        virtual_sessions="no",
        in_network_carriers=["aetna", "anthem_bcbs"],
        accepts_out_of_network=True,
        sliding_scale=True,
        cost="$150–200/session",
        services=["psychotherapy"],
        settings=["outpatient"],
        modalities=["cbt", "emdr"],
        age_groups=["children_0_5"],
        genders=["female"],
        website="https://drsmith.example.com",
    )


def _empty_aff() -> SimpleNamespace:
    return SimpleNamespace(
        in_person_sessions=None,
        virtual_sessions=None,
        in_network_carriers=[],
        accepts_out_of_network=False,
        sliding_scale=False,
        cost=None,
        services=[],
        settings=[],
        modalities=[],
        age_groups=[],
        genders=[],
        website=None,
    )


def test_full_profile_renders_every_row_by_stable_key() -> None:
    tree = _render(_full_aff())
    keys = [row.attributes.get("data-fact") for row in tree.css("div[data-fact]")]
    assert keys == [
        "availability",
        "insurance",
        "cost",
        "services",
        "settings",
        "modalities",
        "age_groups",
        "genders",
        "website",
    ]


def test_rows_carry_human_readable_labels() -> None:
    html = _render(_full_aff()).html or ""
    assert "In-person: Yes" in html
    assert "Virtual: No" in html
    assert "Out-of-network OK" in html
    assert "Sliding scale" in html
    assert "Psychotherapy" in html
    assert "Outpatient" in html
    assert "CBT, EMDR" in html
    assert "https://drsmith.example.com" in html


def test_empty_profile_suppresses_every_row() -> None:
    tree = _render(_empty_aff())
    assert tree.css("div[data-fact]") == []
