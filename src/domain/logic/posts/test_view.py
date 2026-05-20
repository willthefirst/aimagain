"""Tests for the post view helpers (`view.py`)."""

from types import SimpleNamespace

import pytest

from src.domain.logic.posts.view import (
    insurance_posture_for_post,
    post_card_view,
    referral_headline,
)


def _cr_post(network_preference: str, insurance_carrier: str | None = None):
    return SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
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
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
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
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert insurance_posture_for_post(post) is None


# --- referral_headline -------------------------------------------


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
def test_referral_headline_composes_age_and_gender(age, gender, expected):
    detail = SimpleNamespace(age_groups=[age], gender=gender)
    assert referral_headline(detail) == expected


def test_referral_headline_uses_first_age_group_only():
    """CR posts describe one client; the schema allows multi age_groups
    for forward-compat but the headline picks the first value so the
    title stays a single "<noun> (<range>)" phrase."""
    detail = SimpleNamespace(
        age_groups=["adolescents_14_18", "adults_25_64"],
        gender="female",
    )
    assert referral_headline(detail) == "Adolescent female (14–18)"


def test_referral_headline_falls_back_when_age_groups_empty():
    """Defensive — schema requires min-1, but the helper degrades
    gracefully if a future code path hands us an empty list."""
    detail = SimpleNamespace(age_groups=[], gender="male")
    assert referral_headline(detail) == "Client Referral"


# --- post_card_view -----------------------------------------------------
#
# The view-model collapses three kind-specific detail shapes (CR has its
# own location + a scalar gender; PA reads location + insurance off the
# linked Provider; program reads identity off the linked Program) into
# one flat dict that templates iterate over. Tests below build a stub
# post per kind and pin the dict's shape end-to-end. Templates are
# tested separately at the route level.


def _make_cr_post(**detail_overrides):
    """Realistic CR stub. Defaults populate every field with a sensible
    value so tests can override only what they care about."""
    defaults = dict(
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        location_in_person="yes",
        location_virtual="no",
        desired_times=["weekday_morning"],
        age_groups=["adults_25_64"],
        languages=["en", "es"],
        gender="female",
        description="Looking for a therapist who takes BCBS.",
        services=["psychotherapy", "medication_management"],
        treatment_modality="CBT",
        network_preference="in_network_required",
        insurance_carrier="bcbs",
    )
    defaults.update(detail_overrides)
    return SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(**defaults),
    )


def _make_pa_post(*, provider_attrs=None, **detail_overrides):
    """Realistic PA stub. Defaults populate provider + detail fields."""
    p = dict(
        id="prov-1",
        org=SimpleNamespace(name="Acme Counseling"),
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        in_network_carriers=["aetna"],
        accepts_out_of_network=False,
        sliding_scale=True,
        cost="$150/session",
    )
    if provider_attrs:
        p.update(provider_attrs)
    d = dict(
        services=["psychotherapy"],
        settings=["individual"],
        age_groups=["adults_25_64"],
        languages=["en"],
        genders=["female", "non_binary"],
        treatment_modality="DBT",
        description="Accepting new clients.",
        schedule_text="Mon-Wed 9-5",
        desired_times=["weekday_morning"],
        website="https://example.com",
        referral_instructions="Email intake@example.com",
    )
    d.update(detail_overrides)
    return SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            provider=SimpleNamespace(**p),
            **d,
        ),
    )


def _make_program_post(*, program_attrs=None, **detail_overrides):
    p = dict(
        id="prog-1",
        name="RISE IOP",
        state_preference="CT",
        organization=SimpleNamespace(name="Acme Health"),
    )
    if program_attrs:
        p.update(program_attrs)
    d = dict(
        services=["psychotherapy"],
        settings=["group"],
        age_groups=["adolescents_14_18"],
        languages=["en"],
        genders=[],
        treatment_modality="DBT",
        description="Intake cohort opens June 1.",
        schedule_text="M-F 9-3",
        desired_times=["weekday_morning"],
        website="https://riseiop.example.com",
        referral_instructions=None,
    )
    d.update(detail_overrides)
    return SimpleNamespace(
        kind="program_intake",
        intake_detail=SimpleNamespace(
            program=SimpleNamespace(**p),
            **d,
        ),
    )


# --- post_card_view: referral ------------------------------------


def test_view_cr_basics():
    """Per-kind discriminators map to the unified verb vocabulary the
    card's left-edge color and `_services_block` H4 both read from."""
    v = post_card_view(_make_cr_post())
    assert v["kind"] == "referral"
    assert v["kind_verb"] == "Seeking"


def test_view_cr_headline_from_age_and_gender():
    v = post_card_view(_make_cr_post(age_groups=["adults_25_64"], gender="male"))
    assert v["headline"] == "Adult male (25–64)"


def test_view_cr_header_state_is_none_state_lives_in_location_chunk():
    """CR shows state in the demographics column (`location_chunk`),
    not in the header line — the headline already carries the
    identity. Pin `header_state` is intentionally None for CR."""
    v = post_card_view(_make_cr_post())
    assert v["header_state"] is None
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": "11201"}


def test_view_cr_in_person_and_virtual_pull_from_detail_row():
    v = post_card_view(_make_cr_post(location_in_person="yes", location_virtual="no"))
    assert v["in_person"] == "yes"
    assert v["virtual"] == "no"


def test_view_cr_settings_always_empty():
    """CR has no `settings` field on its detail row; the view-model
    returns an empty list so templates can iterate uniformly."""
    v = post_card_view(_make_cr_post())
    assert v["settings"] == []


def test_view_cr_gender_wraps_to_single_element_list():
    """CR holds a scalar `gender`; PA/program hold a `genders` list.
    Wrapping into a list keeps templates' iteration shape uniform —
    the `{% for g in view.genders %}` block works for both kinds."""
    v = post_card_view(_make_cr_post(gender="female"))
    assert v["genders"] == ["female"]


def test_view_cr_missing_gender_yields_empty_list():
    v = post_card_view(_make_cr_post(gender=None))
    assert v["genders"] == []


def test_view_cr_full_address_composes_city_state_zip():
    v = post_card_view(_make_cr_post())
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_cr_cr_only_fields_set_pa_only_fields_none():
    """CR populates `network_preference` / `insurance_carrier`; the
    PA-only fields stay at their None/empty defaults."""
    v = post_card_view(_make_cr_post())
    assert v["network_preference"] == "in_network_required"
    assert v["insurance_carrier"] == "bcbs"
    assert v["sliding_scale"] is None
    assert v["cost"] is None
    assert v["in_network_carriers"] == []
    assert v["accepts_out_of_network"] is None
    assert v["practice_link"] is None
    assert v["program_link"] is None


def test_view_cr_no_referral_section():
    """CR has no `website` / `referral_instructions` fields. The
    detail page's "How to refer" section is PA/program-only."""
    v = post_card_view(_make_cr_post())
    assert v["referral"] is None


# --- post_card_view: opening ------------------------------


def test_view_pa_basics():
    v = post_card_view(_make_pa_post())
    assert v["kind"] == "clinician_opening"
    assert v["kind_verb"] == "Providing"


def test_view_pa_headline_is_org_name_state_from_provider():
    """PA's identity is the practice — `provider.org.name`. State
    surfaces via `location_chunk` (the demographics-column icon-only
    row), matching the CR treatment so referral + opening cards
    consistently locate their location in the same place. The header
    line stays uncluttered for both kinds."""
    v = post_card_view(_make_pa_post())
    assert v["headline"] == "Acme Counseling"
    assert v["header_state"] is None
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": "11201"}


def test_view_pa_in_person_virtual_come_from_provider():
    """PA's session availability lives on the linked Provider, not on
    the post's detail row. The view-model normalizes both kinds onto
    the same `in_person`/`virtual` keys so the card's modality chips
    read from one source."""
    v = post_card_view(
        _make_pa_post(
            provider_attrs={"in_person_sessions": "no", "virtual_sessions": "yes"}
        )
    )
    assert v["in_person"] == "no"
    assert v["virtual"] == "yes"


def test_view_pa_practice_link_carries_id_and_org_name():
    v = post_card_view(_make_pa_post())
    assert v["practice_link"] == {"id": "prov-1", "name": "Acme Counseling"}


def test_view_pa_full_address_from_provider():
    v = post_card_view(_make_pa_post())
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_pa_insurance_fields_from_provider():
    v = post_card_view(_make_pa_post())
    assert v["in_network_carriers"] == ["aetna"]
    assert v["accepts_out_of_network"] is False
    assert v["sliding_scale"] is True
    assert v["cost"] == "$150/session"


def test_view_pa_settings_populated_genders_as_list():
    v = post_card_view(_make_pa_post())
    assert v["settings"] == ["individual"]
    assert v["genders"] == ["female", "non_binary"]


def test_view_pa_referral_set_when_either_field_present():
    v = post_card_view(_make_pa_post())
    assert v["referral"] == {
        "website": "https://example.com",
        "instructions": "Email intake@example.com",
    }


def test_view_pa_referral_none_when_both_empty():
    v = post_card_view(_make_pa_post(website=None, referral_instructions=None))
    assert v["referral"] is None


def test_view_pa_location_chunk_pulled_from_provider():
    """PA's `location_chunk` reads city/state/zip from the linked
    Provider so the listing card renders the same "Location" row
    referral cards do. Detail page still gets the full address via
    `full_address` for the expanded rows."""
    v = post_card_view(_make_pa_post())
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": "11201"}
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_pa_no_location_chunk_when_provider_missing():
    """Defensive — a PA stub without a `provider` relationship returns
    `location_chunk=None` instead of crashing. Mirrors the same
    defensive path the existing PA-missing-provider test covers for
    other provider-derived fields."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            provider=None,
            services=[],
            settings=[],
            age_groups=[],
            languages=[],
            genders=[],
            treatment_modality=None,
            description=None,
            schedule_text=None,
            desired_times=[],
            website=None,
            referral_instructions=None,
        ),
    )
    v = post_card_view(post)
    assert v["location_chunk"] is None


# --- post_card_view: intake -------------------------------


def test_view_program_basics():
    v = post_card_view(_make_program_post())
    assert v["kind"] == "program_intake"
    assert v["kind_verb"] == "Providing"


def test_view_program_headline_is_program_name_state_from_program():
    v = post_card_view(_make_program_post())
    assert v["headline"] == "RISE IOP"
    assert v["header_state"] == "CT"


def test_view_program_link_carries_id_and_name():
    v = post_card_view(_make_program_post())
    assert v["program_link"] == {"id": "prog-1", "name": "RISE IOP"}


def test_view_program_organization_name_exposed_separately():
    """Detail page surfaces the owning Org's name as a separate row
    below the Program link. The view-model exposes it as a flat
    field so the template doesn't reach for `prog.organization.name`."""
    v = post_card_view(_make_program_post())
    assert v["organization_name"] == "Acme Health"


def test_view_program_no_in_person_virtual_no_insurance_no_address():
    """Program-availability has no in-person/virtual posture (the
    Program doesn't track session format today), no insurance posture
    (insurance lives on Provider, not Program), and no location of
    its own (the linked Program's `state_preference` surfaces via
    `header_state` instead)."""
    v = post_card_view(_make_program_post())
    assert v["in_person"] is None
    assert v["virtual"] is None
    assert v["insurance_posture"] is None
    assert v["full_address"] is None
    assert v["location_chunk"] is None


# --- post_card_view: defensiveness --------------------------------------


def test_view_unknown_kind_returns_base_skeleton():
    """An unregistered kind returns the all-None skeleton — templates
    render nothing rather than crashing on a missing detail relationship."""
    v = post_card_view(SimpleNamespace(kind="mystery"))
    assert v["kind"] == "mystery"
    assert v["kind_verb"] is None
    assert v["headline"] is None
    assert v["services"] == []


def test_view_cr_missing_detail_returns_base_skeleton():
    """A CR post with no detail relationship (shouldn't happen at
    rest, but the helper stays defensive for stub data) returns the
    skeleton with kind/kind_verb still populated."""
    v = post_card_view(SimpleNamespace(kind="referral", referral_detail=None))
    assert v["kind"] == "referral"
    assert v["kind_verb"] == "Seeking"
    assert v["headline"] is None
    assert v["location_chunk"] is None


def test_view_pa_missing_provider_returns_partial_view():
    """PA's detail has a `provider` relationship that could be None
    in test stubs. View-model populates the detail-row fields it can
    and leaves provider-derived fields at None."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            provider=None,
            services=["psychotherapy"],
            settings=[],
            age_groups=[],
            languages=[],
            genders=[],
            treatment_modality=None,
            description="x",
            schedule_text=None,
            desired_times=[],
            website=None,
            referral_instructions=None,
        ),
    )
    v = post_card_view(post)
    assert v["headline"] is None
    assert v["header_state"] is None
    assert v["full_address"] is None
    assert v["practice_link"] is None
    assert v["sliding_scale"] is None
    # Detail-row fields independent of the provider relationship still
    # populate so the card can render whatever it can.
    assert v["services"] == ["psychotherapy"]
    assert v["description"] == "x"


def test_view_returns_dict_for_jinja_attribute_access():
    """Templates use ``view.field_name`` syntax — Jinja resolves this
    to ``view['field_name']`` on a dict. Pin that the function returns
    a dict (not a NamedTuple or dataclass) so the access pattern
    works without surprises."""
    v = post_card_view(_make_cr_post())
    assert isinstance(v, dict)
    assert v["kind"] == "referral"
