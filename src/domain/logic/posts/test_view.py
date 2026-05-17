"""Tests for the post view helpers (`view.py`)."""

from types import SimpleNamespace

import pytest

from src.domain.logic.posts.view import (
    client_referral_headline,
    insurance_posture_for_post,
)


def _cr_post(network_preference: str, insurance_carrier: str | None = None):
    return SimpleNamespace(
        kind="client_referral",
        client_referral_detail=SimpleNamespace(
            network_preference=network_preference,
            insurance_carrier=insurance_carrier,
        ),
    )


def _pa_post(**provider_attrs):
    provider_attrs.setdefault("in_network_carriers", [])
    provider_attrs.setdefault("accepts_out_of_network", False)
    provider_attrs.setdefault("sliding_scale", False)
    provider_attrs.setdefault("cost", None)
    return SimpleNamespace(
        kind="provider_availability",
        provider_availability_detail=SimpleNamespace(
            provider=SimpleNamespace(**provider_attrs),
        ),
    )


@pytest.mark.parametrize(
    "storage,expected",
    [
        ("in_network_required", "in_network"),
        ("in_network_preferred", "out_of_network"),
        ("no_preference", "self_pay"),
    ],
)
def test_cr_posture_maps_each_network_preference(storage, expected):
    """`network_preference` collapses to one of the unified
    `INSURANCE_POSTURES` values for the listing-row badge. The carrier
    is irrelevant to the posture — same posture whether it's set or
    null."""
    assert insurance_posture_for_post(_cr_post(storage)) == expected
    assert insurance_posture_for_post(_cr_post(storage, "cigna")) == expected


def test_pa_posture_prefers_in_network_when_set():
    """In-network is the highest-signal posture; show it even when the
    provider also accepts out-of-network or offers sliding scale."""
    post = _pa_post(
        in_network_carriers=["aetna"],
        accepts_out_of_network=True,
        sliding_scale=True,
    )
    assert insurance_posture_for_post(post) == "in_network"


def test_pa_posture_falls_back_to_oon_then_self_pay_then_contact():
    assert (
        insurance_posture_for_post(_pa_post(accepts_out_of_network=True))
        == "out_of_network"
    )
    assert insurance_posture_for_post(_pa_post(sliding_scale=True)) == "self_pay"
    assert insurance_posture_for_post(_pa_post(cost="$150/session")) == "self_pay"
    # No flags set at all → the post offers no insurance signal; the row
    # macro renders the help glyph so the reader knows to ask.
    assert insurance_posture_for_post(_pa_post()) == "please_contact"


def test_posture_returns_none_for_unknown_kind():
    """An unregistered kind has no detail row; the helper returns None
    and the row macro omits the insurance chunk."""
    post = SimpleNamespace(kind="mystery")
    assert insurance_posture_for_post(post) is None


def test_posture_returns_none_when_detail_missing():
    post = SimpleNamespace(kind="client_referral", client_referral_detail=None)
    assert insurance_posture_for_post(post) is None


# --- client_referral_headline -------------------------------------------


@pytest.mark.parametrize(
    "age,gender,expected",
    [
        ("adults_25_64", "male", "Adult male (25–64)"),
        ("adolescents_14_18", "female", "Adolescent female (14–18)"),
        ("young_adults_19_24", "non_binary", "Young adult non-binary (19–24)"),
        ("adults_25_64", "trans_female", "Adult trans woman (25–64)"),
        ("adults_25_64", "trans_male", "Adult trans man (25–64)"),
        # Gender values that don't slot in as an adjective drop the
        # gender word entirely; the headline becomes "<noun> (<range>)".
        ("adults_25_64", "prefer_not_to_say", "Adult (25–64)"),
        ("adults_25_64", "gender_diverse", "Adult (25–64)"),
        ("older_adults_65_plus", "prefer_not_to_say", "Older adult (65+)"),
    ],
)
def test_client_referral_headline_composes_age_and_gender(age, gender, expected):
    detail = SimpleNamespace(age_groups=[age], gender=gender)
    assert client_referral_headline(detail) == expected


def test_client_referral_headline_uses_first_age_group_only():
    """CR posts describe one client; the schema allows multi age_groups
    for forward-compat but the headline picks the first value so the
    title stays a single "<noun> (<range>)" phrase."""
    detail = SimpleNamespace(
        age_groups=["adolescents_14_18", "adults_25_64"],
        gender="female",
    )
    assert client_referral_headline(detail) == "Adolescent female (14–18)"


def test_client_referral_headline_falls_back_when_age_groups_empty():
    """Defensive — schema requires min-1, but the helper degrades
    gracefully if a future code path hands us an empty list."""
    detail = SimpleNamespace(age_groups=[], gender="male")
    assert client_referral_headline(detail) == "Client Referral"
