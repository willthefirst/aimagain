"""Tests for the post view helpers (`view.py`)."""

from types import SimpleNamespace

import pytest

from src.domain.logic.posts.view import (
    _LIST_PASSTHROUGH,
    _SCALAR_PASSTHROUGH,
    insurance_posture_for_post,
    post_card_view,
    post_feed_headline,
    post_row_summary,
    referral_headline,
)


def _cr_post(
    *,
    accepts_in_network: bool = False,
    accepts_out_of_network_superbill: bool = False,
    accepts_private_pay: bool = False,
    insurance_carriers: list[str] | None = None,
):
    return SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            accepts_in_network=accepts_in_network,
            accepts_out_of_network_superbill=accepts_out_of_network_superbill,
            accepts_private_pay=accepts_private_pay,
            insurance_carriers=insurance_carriers or [],
        ),
    )


def _pa_post(**clinician_attrs):
    clinician_attrs.setdefault("in_network_carriers", [])
    clinician_attrs.setdefault("accepts_out_of_network", False)
    clinician_attrs.setdefault("sliding_scale", False)
    clinician_attrs.setdefault("cost", None)
    return SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=SimpleNamespace(**clinician_attrs),
        ),
    )


def test_cr_posture_prefers_in_network():
    """In-network is the highest-signal payment-path; show it even when
    OON-superbill and private-pay are also accepted (#1358 PR-e)."""
    post = _cr_post(
        accepts_in_network=True,
        accepts_out_of_network_superbill=True,
        accepts_private_pay=True,
    )
    assert insurance_posture_for_post(post) == "in_network"
    # Carrier presence is irrelevant to the posture — same answer with
    # or without `insurance_carriers`.
    post_with_carrier = _cr_post(accepts_in_network=True, insurance_carriers=["cigna"])
    assert insurance_posture_for_post(post_with_carrier) == "in_network"


def test_cr_posture_falls_back_to_oon_then_private_pay_then_contact():
    """Priority order: in-network > out-of-network-superbill >
    private-pay > please_contact (none set)."""
    assert (
        insurance_posture_for_post(_cr_post(accepts_out_of_network_superbill=True))
        == "out_of_network"
    )
    assert insurance_posture_for_post(_cr_post(accepts_private_pay=True)) == "self_pay"
    # All three booleans false → the referral states no preference;
    # the row macro surfaces the "Contact" glyph.
    assert insurance_posture_for_post(_cr_post()) == "please_contact"


def test_pa_posture_prefers_in_network_when_set():
    """In-network is the highest-signal posture; show it even when the
    clinician also accepts out-of-network or offers sliding scale."""
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
# linked Clinician; program reads identity off the linked Program) into
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
        accepts_in_network=True,
        accepts_out_of_network_superbill=False,
        accepts_private_pay=False,
        insurance_carriers=["anthem_bcbs"],
    )
    defaults.update(detail_overrides)
    return SimpleNamespace(
        kind="referral",
        owner=SimpleNamespace(
            clinicians=[SimpleNamespace(first_name="Carlos", last_name="Rivera")]
        ),
        referral_detail=SimpleNamespace(**defaults),
    )


def _make_pa_post(*, clinician_attrs=None, **detail_overrides):
    """Realistic PA stub. Defaults populate clinician + detail fields."""
    p = dict(
        id="prov-1",
        first_name="Jane",
        last_name="Smith",
        org=SimpleNamespace(id="org-1", name="Acme Counseling"),
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
    if clinician_attrs:
        p.update(clinician_attrs)
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
            clinician=SimpleNamespace(**p),
            **d,
        ),
    )


def _make_program_post(*, program_attrs=None, **detail_overrides):
    p = dict(
        id="prog-1",
        name="RISE IOP",
        state_preference="CT",
        organization=SimpleNamespace(id="org-h", name="Acme Health"),
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
    """CR populates payment-paths booleans + `insurance_carriers`
    (#1358 PR-e); the PA-only fields stay at their None/empty
    defaults."""
    v = post_card_view(_make_cr_post())
    assert v["accepts_in_network"] is True
    assert v["accepts_out_of_network_superbill"] is False
    assert v["accepts_private_pay"] is False
    assert v["insurance_carriers"] == ["anthem_bcbs"]
    assert v["sliding_scale"] is None
    assert v["cost"] is None
    assert v["in_network_carriers"] == []
    assert v["accepts_out_of_network"] is None
    assert v["practice_link"] is None
    assert v["program_link"] is None
    assert v["organization_link"] is None


def test_view_cr_no_referral_section():
    """CR has no `website` / `referral_instructions` fields. The
    detail page's "How to refer" section is PA/program-only."""
    v = post_card_view(_make_cr_post())
    assert v["referral"] is None


def test_view_cr_subject_when_set():
    """`subject` propagates from the detail row into the view dict."""
    v = post_card_view(_make_cr_post(subject="Anxiety + ADHD evaluation"))
    assert v["subject"] == "Anxiety + ADHD evaluation"


def test_view_cr_subject_none_when_absent():
    """No subject on the detail row → `subject` key is None in view."""
    v = post_card_view(_make_cr_post(subject=None))
    assert v["subject"] is None


# --- post_card_view: opening ------------------------------


def test_view_pa_basics():
    v = post_card_view(_make_pa_post())
    assert v["kind"] == "clinician_opening"
    assert v["kind_verb"] == "Providing"


def test_view_pa_headline_is_org_name_state_from_clinician():
    """PA's identity is the practice — `clinician.org.name`. State
    surfaces via `location_chunk` (the demographics-column icon-only
    row), matching the CR treatment so referral + opening cards
    consistently locate their location in the same place. The header
    line stays uncluttered for both kinds."""
    v = post_card_view(_make_pa_post())
    assert v["headline"] == "Acme Counseling"
    assert v["header_state"] is None
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": "11201"}


def test_view_pa_in_person_virtual_come_from_clinician():
    """PA's session availability lives on the linked Clinician, not on
    the post's detail row. The view-model normalizes both kinds onto
    the same `in_person`/`virtual` keys so the card's modality chips
    read from one source."""
    v = post_card_view(
        _make_pa_post(
            clinician_attrs={"in_person_sessions": "no", "virtual_sessions": "yes"}
        )
    )
    assert v["in_person"] == "no"
    assert v["virtual"] == "yes"


def test_view_pa_practice_link_carries_id_and_org_name():
    v = post_card_view(_make_pa_post())
    assert v["practice_link"] == {"id": "prov-1", "name": "Acme Counseling"}


def test_view_pa_organization_link_carries_org_id_and_name():
    """Opening's org link reads through `clinician.org` so the detail
    page's `Organization` row is a one-click jump to the owning org."""
    v = post_card_view(_make_pa_post())
    assert v["organization_link"] == {"id": "org-1", "name": "Acme Counseling"}


def test_view_pa_full_address_from_clinician():
    v = post_card_view(_make_pa_post())
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_pa_insurance_fields_from_clinician():
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


def test_view_pa_subject_when_set():
    v = post_card_view(_make_pa_post(subject="Spring intake cohort"))
    assert v["subject"] == "Spring intake cohort"


def test_view_pa_subject_none_when_absent():
    v = post_card_view(_make_pa_post(subject=None))
    assert v["subject"] is None


def test_view_pa_location_chunk_pulled_from_clinician():
    """PA's `location_chunk` reads city/state/zip from the linked
    Clinician so the listing card renders the same "Location" row
    referral cards do. Detail page still gets the full address via
    `full_address` for the expanded rows."""
    v = post_card_view(_make_pa_post())
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": "11201"}
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_pa_no_location_chunk_when_clinician_missing():
    """Defensive — a PA stub without a `clinician` relationship returns
    `location_chunk=None` instead of crashing. Mirrors the same
    defensive path the existing PA-missing-clinician test covers for
    other clinician-derived fields."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
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


def test_view_program_organization_link_carries_org_id_and_name():
    """Detail page surfaces the owning Org as a clickable link below
    the Program link — the view-model exposes `{id, name}` so the
    template renders an `<a>` (mirrors `practice_link` /
    `program_link`); a one-click jump to `/organizations/{id}`."""
    v = post_card_view(_make_program_post())
    assert v["organization_link"] == {"id": "org-h", "name": "Acme Health"}


def test_view_program_no_in_person_virtual_no_insurance_no_address():
    """Program-availability has no in-person/virtual posture (the
    Program doesn't track session format today), no insurance posture
    (insurance lives on Clinician, not Program), and no location of
    its own (the linked Program's `state_preference` surfaces via
    `header_state` instead)."""
    v = post_card_view(_make_program_post())
    assert v["in_person"] is None
    assert v["virtual"] is None
    assert v["insurance_posture"] is None
    assert v["full_address"] is None
    assert v["location_chunk"] is None


# --- post_card_view: modalities -----------------------------------------


def test_view_cr_modalities_populated():
    post = _make_cr_post(modalities=["cbt", "dbt"])
    v = post_card_view(post)
    assert v["modalities"] == ["cbt", "dbt"]


def test_view_cr_modalities_empty_by_default():
    post = _make_cr_post(modalities=[])
    v = post_card_view(post)
    assert v["modalities"] == []


def test_view_pa_modalities_populated():
    post = _make_pa_post(modalities=["emdr", "ifs"])
    v = post_card_view(post)
    assert v["modalities"] == ["emdr", "ifs"]


def test_view_program_modalities_populated():
    post = _make_program_post(modalities=["somatic"])
    v = post_card_view(post)
    assert v["modalities"] == ["somatic"]


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


def test_view_pa_missing_clinician_returns_partial_view():
    """PA's detail has a `clinician` relationship that could be None
    in test stubs. View-model populates the detail-row fields it can
    and leaves clinician-derived fields at None."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
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
    assert v["organization_link"] is None
    assert v["sliding_scale"] is None
    # Detail-row fields independent of the clinician relationship still
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


# --- post_card_view: poster_name ----------------------------------------


def test_poster_name_opening_uses_clinician_first_last():
    v = post_card_view(_make_pa_post())
    assert v["poster_name"] == "Jane Smith"


def test_poster_name_opening_partial_name():
    v = post_card_view(
        _make_pa_post(clinician_attrs={"first_name": "Jane", "last_name": None})
    )
    assert v["poster_name"] == "Jane"


def test_poster_name_opening_none_when_no_names():
    v = post_card_view(
        _make_pa_post(clinician_attrs={"first_name": None, "last_name": None})
    )
    assert v["poster_name"] is None


def test_poster_name_opening_none_when_no_clinician():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
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
    assert post_card_view(post)["poster_name"] is None


def test_poster_name_intake_uses_org_name():
    v = post_card_view(_make_program_post())
    assert v["poster_name"] == "Acme Health"


def test_poster_name_intake_none_when_no_org():
    v = post_card_view(_make_program_post(program_attrs={"organization": None}))
    assert v["poster_name"] is None


def test_poster_name_referral_uses_owner_clinician_name():
    v = post_card_view(_make_cr_post())
    assert v["poster_name"] == "Carlos Rivera"


def test_poster_name_referral_none_when_no_owner_clinicians():
    post = _make_cr_post()
    post.owner = SimpleNamespace(clinicians=[])
    assert post_card_view(post)["poster_name"] is None


def test_poster_name_referral_none_when_clinician_has_no_name():
    post = _make_cr_post()
    post.owner = SimpleNamespace(
        clinicians=[SimpleNamespace(first_name=None, last_name=None)]
    )
    assert post_card_view(post)["poster_name"] is None


# --- post_row_summary ---------------------------------------------------


def test_row_summary_referral_description_carrier_city():
    """Primary path: description + first carrier label + city joined
    with ' · ' (#1358 PR-e — `insurance_carriers` is a list; the
    row summary picks the first to fit the single-line layout)."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description="Complex PTSD, seeking weekly EMDR",
            insurance_carriers=["aetna"],
            location_city="Berkeley",
            age_groups=["adults_25_64"],
            gender="female",
        ),
    )
    assert (
        post_row_summary(post) == "Complex PTSD, seeking weekly EMDR · Aetna · Berkeley"
    )


def test_row_summary_referral_no_carrier_no_city():
    """When carriers list is empty and city is absent only the
    description is returned."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description="Needs a therapist",
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
            gender="male",
        ),
    )
    assert post_row_summary(post) == "Needs a therapist"


def test_row_summary_referral_no_description_falls_back_to_headline():
    """When description is absent the age+gender headline is used."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description=None,
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
            gender="male",
        ),
    )
    assert post_row_summary(post) == "Adult male (25–64)"


def test_row_summary_referral_truncates_long_description():
    """Descriptions longer than 100 chars are truncated so rows stay readable."""
    long_desc = "x" * 150
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description=long_desc,
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
            gender=None,
        ),
    )
    summary = post_row_summary(post)
    assert len(summary) == 100
    assert summary == "x" * 100


def test_row_summary_referral_missing_detail():
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert post_row_summary(post) == "Referral"


def test_row_summary_opening_with_description_and_settings():
    """Opening with description + first settings label + sliding scale."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description="2 slots open",
            settings=["outpatient"],
            age_groups=[],
            services=[],
            clinician=SimpleNamespace(sliding_scale=True),
        ),
    )
    assert post_row_summary(post) == "2 slots open · Outpatient · sliding scale"


def test_row_summary_opening_no_description_builds_from_fields():
    """When opening has no description, age + service labels are used."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description=None,
            settings=[],
            age_groups=["adults_25_64"],
            services=["psychotherapy"],
            clinician=SimpleNamespace(sliding_scale=False),
        ),
    )
    summary = post_row_summary(post)
    assert "Adult (25–64)" in summary
    assert "Psychotherapy" in summary


def test_row_summary_opening_no_sliding_scale():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description="Accepting new clients",
            settings=[],
            age_groups=[],
            services=[],
            clinician=SimpleNamespace(sliding_scale=False),
        ),
    )
    assert post_row_summary(post) == "Accepting new clients"


def test_row_summary_opening_missing_detail():
    post = SimpleNamespace(kind="clinician_opening", opening_detail=None)
    assert post_row_summary(post) == "Opening"


def test_row_summary_program_name_and_description():
    post = SimpleNamespace(
        kind="program_intake",
        intake_detail=SimpleNamespace(
            program=SimpleNamespace(name="RISE IOP"),
            description="Cohort starts June 1",
        ),
    )
    assert post_row_summary(post) == "RISE IOP · Cohort starts June 1"


def test_row_summary_unknown_kind_returns_empty_string():
    post = SimpleNamespace(kind="mystery")
    assert post_row_summary(post) == ""


# --- post_feed_headline -------------------------------------------------


def test_feed_headline_referral_with_services():
    """Demographics form the left half; up to 2 service labels the right half."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            age_groups=["adults_25_64"],
            gender="female",
            services=["psychotherapy", "medication_management"],
        ),
    )
    assert (
        post_feed_headline(post)
        == "Adult female (25–64) — Psychotherapy, Medication management"
    )


def test_feed_headline_referral_no_services_returns_demographics_only():
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            age_groups=["adolescents_14_18"],
            gender="male",
            services=[],
        ),
    )
    assert post_feed_headline(post) == "Adolescent male (14–18)"


def test_feed_headline_referral_caps_services_at_two():
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            age_groups=["adults_25_64"],
            gender="non_binary",
            services=["evaluation", "psychotherapy", "case_management"],
        ),
    )
    headline = post_feed_headline(post)
    # Only first two services should appear; third is dropped.
    assert "Evaluation, Psychotherapy" in headline
    assert "Case management" not in headline


def test_feed_headline_referral_missing_detail_returns_fallback():
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert post_feed_headline(post) == "Referral"


def test_feed_headline_opening_with_services():
    """Practice name forms the left half; service labels the right half."""
    post = _make_pa_post()
    headline = post_feed_headline(post)
    assert headline.startswith("Acme Counseling — ")
    assert "Psychotherapy" in headline


def test_feed_headline_opening_falls_back_to_settings_when_no_services():
    """When an opening carries no services, settings labels are used for the focus."""
    post = _make_pa_post(services=[], settings=["outpatient", "iop"])
    headline = post_feed_headline(post)
    assert "Outpatient" in headline
    assert "IOP" in headline


def test_feed_headline_opening_practice_name_only_when_no_focus():
    """Practice name alone is returned when both services and settings are empty."""
    post = _make_pa_post(services=[], settings=[])
    assert post_feed_headline(post) == "Acme Counseling"


def test_feed_headline_opening_missing_detail_returns_fallback():
    post = SimpleNamespace(kind="clinician_opening", opening_detail=None)
    assert post_feed_headline(post) == "Opening"


def test_feed_headline_opening_missing_clinician_returns_fallback():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
            services=["psychotherapy"],
            settings=[],
        ),
    )
    # Practice name cannot be derived; headline falls back to "Opening — <service>".
    headline = post_feed_headline(post)
    assert "Psychotherapy" in headline


def test_feed_headline_program_with_services():
    post = _make_program_post()
    headline = post_feed_headline(post)
    assert headline.startswith("RISE IOP — ")
    assert "Psychotherapy" in headline


def test_feed_headline_program_no_services_returns_name_only():
    post = _make_program_post(services=[])
    assert post_feed_headline(post) == "RISE IOP"


def test_feed_headline_unknown_kind_returns_empty_string():
    post = SimpleNamespace(kind="mystery")
    assert post_feed_headline(post) == ""


# --- subject override ---------------------------------------------------


def test_feed_headline_referral_subject_overrides_auto_generation():
    """When subject is set on a referral, it is returned as-is."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            subject="Child female (0–5) — Group therapy",
            age_groups=["children_0_5"],
            gender="female",
            services=["group_therapy"],
        ),
    )
    assert post_feed_headline(post) == "Child female (0–5) — Group therapy"


def test_feed_headline_referral_none_subject_falls_back_to_auto():
    """When subject is None, auto-generation runs normally."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            subject=None,
            age_groups=["adults_25_64"],
            gender="female",
            services=["psychotherapy"],
        ),
    )
    assert post_feed_headline(post) == "Adult female (25–64) — Psychotherapy"


def test_feed_headline_opening_subject_overrides_auto_generation():
    """When subject is set on an opening, it is returned as-is."""
    post = _make_pa_post()
    post.opening_detail.subject = "3 slots — adults, relational/psychodynamic"
    assert post_feed_headline(post) == "3 slots — adults, relational/psychodynamic"


def test_feed_headline_opening_none_subject_falls_back_to_auto():
    """When subject is None on an opening, practice name + services are used."""
    post = _make_pa_post()
    post.opening_detail.subject = None
    headline = post_feed_headline(post)
    assert headline.startswith("Acme Counseling — ")


# --- post_card_view: detail-row auto-forward ---------------------
# The passthrough fields are copied off the detail row by a single
# table-driven helper, not hand-listed per kind. These pin that
# contract so a new passthrough field can't be silently dropped from
# one kind's block: add it to `_SCALAR_PASSTHROUGH` / `_LIST_PASSTHROUGH`
# and it forwards for every kind that has the attribute.


@pytest.mark.parametrize(
    "make_post",
    [_make_cr_post, _make_pa_post, _make_program_post],
    ids=["referral", "opening", "intake"],
)
def test_passthrough_keys_present_for_every_kind(make_post):
    """Every declared passthrough field surfaces in the view for every
    kind — scalars as a value-or-None key, lists as a (possibly empty)
    list. `genders` is excluded: referral overrides it from its single
    `gender` column, so its forwarded value is recomputed downstream."""
    v = post_card_view(make_post())
    for view_key in _SCALAR_PASSTHROUGH:
        assert view_key in v
    for view_key in _LIST_PASSTHROUGH:
        assert isinstance(v[view_key], list)


def test_passthrough_forwards_detail_values_for_opening():
    """An opening's detail-row scalars/lists land on the view verbatim,
    proving the helper reads the right attributes (no rename drift)."""
    v = post_card_view(
        _make_pa_post(
            description="Forwarded description",
            schedule_text="Forwarded schedule",
            treatment_modality="ACT",
            services=["psychotherapy", "group_therapy"],
            settings=["group"],
        )
    )
    assert v["description"] == "Forwarded description"
    assert v["schedule_text"] == "Forwarded schedule"
    assert v["treatment_modality"] == "ACT"
    assert v["services"] == ["psychotherapy", "group_therapy"]
    assert v["settings"] == ["group"]


def test_passthrough_missing_attr_falls_back_to_base_default():
    """A referral detail row has no `settings` / `schedule_text`
    columns. The helper uses `getattr(..., None)`, so those keep the
    base defaults (`[]` for lists, `None` for scalars) rather than
    raising — that's why referral can share the same forwarding pass."""
    v = post_card_view(_make_cr_post())
    assert v["settings"] == []
    assert v["schedule_text"] is None
