"""Tests for the provider view helpers (`view.py`)."""

from types import SimpleNamespace

from src.domain.logic.clinicians.view import (
    _insurance_summary,
    affiliation_card_view,
    provider_card_view,
)


def _stub_affiliation(**overrides):
    """Realistic Affiliation stub. Mirrors the per-role columns on the
    real ``Affiliation`` ORM row plus the ``org`` relationship the
    view-model reads through.

    ``org`` defaults to a SimpleNamespace; pass ``org=None`` to drop the
    relationship for an "org missing" branch test.
    """
    defaults = dict(
        org_id="org-1",
        org=SimpleNamespace(name="Acme Counseling"),
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        in_network_carriers=["aetna"],
        accepts_out_of_network=False,
        sliding_scale=False,
        cost=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _stub_provider(**overrides):
    """Realistic Provider stub. Defaults populate every field with a
    sensible value so tests can override only what they care about.

    `npi` lives on the linked ``Clinician`` after #629 PR 1 — the view
    reads ``provider.clinician.npi``. Tests still pass `npi=...` for
    ergonomics; the stub builder rolls the kwarg into a nested
    ``clinician`` SimpleNamespace so the view sees the same shape it
    sees in production.

    ``affiliations`` defaults to an empty list — most tests pin the
    flat per-role keys (sourced via ``_role_attr`` from the stub's own
    attributes or its ``primary_affiliation``) and don't care about the
    stacked-sections list. Pass ``affiliations=[_stub_affiliation(...)]``
    when exercising the detail-page's per-affiliation rendering.
    """
    defaults = dict(
        org_id="org-1",
        org=SimpleNamespace(name="Acme Counseling"),
        npi=None,
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        in_network_carriers=["aetna"],
        accepts_out_of_network=False,
        sliding_scale=False,
        cost=None,
        licensures=[],
        educations=[],
        certifications=[],
        affiliations=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# Address composition lives in `src/framework/rendering/address.py`;
# its full unit-test matrix is `src/framework/rendering/test_address.py`.
# `provider_card_view`'s integration with that helper is exercised by
# the card-view tests below.


# --- _insurance_summary ------------------------------------------------


def test_insurance_summary_self_pay_when_no_carriers_no_oon():
    p = _stub_provider(in_network_carriers=[], accepts_out_of_network=False)
    assert _insurance_summary(p) == "Self-pay only"


def test_insurance_summary_in_network_only():
    p = _stub_provider(
        in_network_carriers=["aetna", "anthem_bcbs"], accepts_out_of_network=False
    )
    assert _insurance_summary(p) == "In-network (Aetna, Anthem / BCBS)"


def test_insurance_summary_oon_only():
    p = _stub_provider(in_network_carriers=[], accepts_out_of_network=True)
    assert _insurance_summary(p) == "Out-of-network"


def test_insurance_summary_both():
    p = _stub_provider(in_network_carriers=["aetna"], accepts_out_of_network=True)
    assert _insurance_summary(p) == "In-network (Aetna) · Out-of-network"


# --- _insurance_summary across multiple affiliations -------------------
#
# After #642 PR 3 the directory listing reads `_insurance_summary` and
# expects it to union across every affiliation the Provider holds.


def test_insurance_summary_unions_carriers_across_affiliations():
    """Two affiliations each with their own in-network carrier roll up
    into one ``In-network (...)`` clause with both carriers listed.
    Order is first-seen-per-affiliation, then within-affiliation order."""
    a = _stub_affiliation(in_network_carriers=["aetna"], accepts_out_of_network=False)
    b = _stub_affiliation(
        in_network_carriers=["anthem_bcbs"], accepts_out_of_network=False
    )
    p = _stub_provider(affiliations=[a, b])
    assert _insurance_summary(p) == "In-network (Aetna, Anthem / BCBS)"


def test_insurance_summary_dedupes_repeated_carriers():
    """A clinician with two affiliations that both take Aetna shouldn't
    show ``Aetna, Aetna`` — carrier codes dedupe across the union."""
    a = _stub_affiliation(in_network_carriers=["aetna"], accepts_out_of_network=False)
    b = _stub_affiliation(in_network_carriers=["aetna"], accepts_out_of_network=False)
    p = _stub_provider(affiliations=[a, b])
    assert _insurance_summary(p) == "In-network (Aetna)"


def test_insurance_summary_oon_if_any_affiliation_accepts():
    """Mixed posture: one affiliation accepts OON, the other doesn't.
    The roll-up still says Out-of-network (``any``, not ``all``)."""
    a = _stub_affiliation(in_network_carriers=[], accepts_out_of_network=True)
    b = _stub_affiliation(in_network_carriers=[], accepts_out_of_network=False)
    p = _stub_provider(affiliations=[a, b])
    assert _insurance_summary(p) == "Out-of-network"


def test_insurance_summary_self_pay_when_all_affiliations_self_pay():
    """Every affiliation is self-pay-only → roll-up is ``Self-pay only``."""
    a = _stub_affiliation(in_network_carriers=[], accepts_out_of_network=False)
    b = _stub_affiliation(in_network_carriers=[], accepts_out_of_network=False)
    p = _stub_provider(affiliations=[a, b])
    assert _insurance_summary(p) == "Self-pay only"


def test_insurance_summary_appends_sliding_when_any_affiliation_has_it():
    """Any affiliation offering sliding scale surfaces in the row as a
    trailing ``· sliding`` so the cell carries the full posture in one
    string (the row macro no longer renders sliding as a separate
    badge)."""
    a = _stub_affiliation(
        in_network_carriers=["aetna"], accepts_out_of_network=False, sliding_scale=False
    )
    b = _stub_affiliation(
        in_network_carriers=[], accepts_out_of_network=False, sliding_scale=True
    )
    p = _stub_provider(affiliations=[a, b])
    assert _insurance_summary(p) == "In-network (Aetna) · sliding"


def test_insurance_summary_full_combination():
    """The "everything on" case: in-network carriers from each
    affiliation, at least one accepts OON, at least one has sliding
    scale. All three clauses appear, joined by ``· `` in order."""
    a = _stub_affiliation(
        in_network_carriers=["aetna"],
        accepts_out_of_network=False,
        sliding_scale=False,
    )
    b = _stub_affiliation(
        in_network_carriers=["anthem_bcbs"],
        accepts_out_of_network=True,
        sliding_scale=True,
    )
    p = _stub_provider(affiliations=[a, b])
    assert (
        _insurance_summary(p)
        == "In-network (Aetna, Anthem / BCBS) · Out-of-network · sliding"
    )


def test_insurance_summary_sliding_alone_with_self_pay():
    """A clinician whose only insurance posture across affiliations is
    sliding-scale-only self-pay still surfaces sliding. ``Self-pay only``
    sits in the base; ``· sliding`` trails."""
    a = _stub_affiliation(
        in_network_carriers=[], accepts_out_of_network=False, sliding_scale=True
    )
    p = _stub_provider(affiliations=[a])
    assert _insurance_summary(p) == "Self-pay only · sliding"


# --- provider_card_view ------------------------------------------------


def test_view_practice_name_from_org():
    v = provider_card_view(_stub_provider())
    assert v["practice_name"] == "Acme Counseling"


def test_view_practice_url_links_to_owning_org():
    v = provider_card_view(_stub_provider(org_id="abc-123"))
    assert v["practice_url"] == "/organizations/abc-123"


def test_view_full_address_composes_location_columns():
    v = provider_card_view(_stub_provider())
    assert v["full_address"] == "Brooklyn, NY 11201"


def test_view_in_person_and_virtual_resolved_to_display_labels():
    """Template doesn't need to call LOCATION_AVAILABILITY_LABELS — the
    view-model pre-resolves to display strings."""
    v = provider_card_view(
        _stub_provider(in_person_sessions="yes", virtual_sessions="no")
    )
    assert v["in_person_label"] == "Yes"
    assert v["virtual_label"] == "No"


def test_view_insurance_summary_collapses_three_conditionals():
    """The old template had three nested conditionals to compose this
    string. The view-model collapses to one string the template emits
    directly."""
    p = _stub_provider(in_network_carriers=["aetna"], accepts_out_of_network=True)
    v = provider_card_view(p)
    assert v["insurance_summary"] == "In-network (Aetna) · Out-of-network"


def test_view_sliding_scale_label_yes():
    v = provider_card_view(_stub_provider(sliding_scale=True))
    assert v["sliding_scale_label"] == "Yes"


def test_view_sliding_scale_label_no():
    v = provider_card_view(_stub_provider(sliding_scale=False))
    assert v["sliding_scale_label"] == "No"


def test_view_passes_through_optional_cost_and_npi():
    v = provider_card_view(_stub_provider(cost="$150/session", npi="1234567890"))
    assert v["cost"] == "$150/session"
    assert v["npi"] == "1234567890"


def test_view_returns_empty_list_for_missing_credentials():
    """The template iterates `view.licensures / educations / certifications`
    via `{% for ... %}`; empty lists render nothing without needing a
    None-guard."""
    v = provider_card_view(_stub_provider())
    assert v["licensures"] == []
    assert v["educations"] == []
    assert v["certifications"] == []


def test_view_returns_dict_for_jinja_attribute_access():
    """Templates use ``view.field`` syntax — Jinja resolves to
    ``__getitem__`` on dicts. Pin that the function returns a dict."""
    v = provider_card_view(_stub_provider())
    assert isinstance(v, dict)
    assert v["practice_name"] == "Acme Counseling"


def test_view_prefers_affiliation_over_legacy_provider_columns():
    """Regression for #629 PR 3 — per-role attrs source from
    ``provider.primary_affiliation`` first, falling back to the legacy
    column on ``provider`` only when the affiliation is absent or
    has no value for the field.

    After #642 PR 1, a Provider may hold multiple Affiliations; the
    view-model reads through ``primary_affiliation`` (the oldest by
    ``created_at``) so the listing's per-row dereferencing is
    deterministic — PR 3 (issue #642) collapses the listing to one
    row per Clinician with stacked affiliations. The test pins the
    precedence by giving the two sides disagreeing values and
    asserting the affiliation value wins.
    """
    provider = _stub_provider(
        # Legacy columns on `provider` carry the "old" values
        in_person_sessions="no",
        virtual_sessions="no",
        sliding_scale=False,
        cost="$50/session",
        location_city="Old City",
        location_state="NY",
        location_zip="00000",
        in_network_carriers=[],
        accepts_out_of_network=False,
        # `primary_affiliation` carries the post-PR-3 source of truth.
        primary_affiliation=SimpleNamespace(
            in_person_sessions="yes",
            virtual_sessions="please_contact",
            sliding_scale=True,
            cost="$200/session",
            location_city="New City",
            location_state="CA",
            location_zip="90210",
            in_network_carriers=["aetna"],
            accepts_out_of_network=True,
        ),
    )
    v = provider_card_view(provider)
    assert v["in_person_label"] is not None
    # affiliation says yes → label maps to the Yes branch, not the
    # legacy "no" → "No" branch.
    assert "yes" in v["in_person_label"].lower() or v["in_person_label"] == "Yes"
    assert v["sliding_scale_label"] == "Yes"
    assert v["cost"] == "$200/session"
    assert "New City" in v["full_address"]
    assert "CA" in v["full_address"]
    assert "90210" in v["full_address"]
    # Affiliation has both Aetna in-network and accepts_oon=True →
    # summary mentions both.
    assert "Aetna" in v["insurance_summary"]
    assert "Out-of-network" in v["insurance_summary"]


# --- affiliation_card_view -----------------------------------------------


def test_affiliation_card_view_shape():
    """`affiliation_card_view(aff)` returns the per-role dict shape one
    stacked-section card on the provider detail page reads from
    (#642 PR 2). Pins the keys the template enumerates so a rename in
    `view.py` is caught here before the template renders blanks."""
    aff = _stub_affiliation(
        org_id="org-7",
        org=SimpleNamespace(name="Bedlam Health"),
        location_city="Queens",
        location_state="NY",
        location_zip="11101",
        in_person_sessions="yes",
        virtual_sessions="no",
        in_network_carriers=["aetna"],
        accepts_out_of_network=True,
        sliding_scale=True,
        cost="$220/session",
    )
    card = affiliation_card_view(aff)
    assert card["org_id"] == "org-7"
    assert card["org_name"] == "Bedlam Health"
    assert card["org_url"] == "/organizations/org-7"
    assert card["full_address"] == "Queens, NY 11101"
    assert card["in_person_label"] == "Yes"
    assert card["virtual_label"] == "No"
    assert card["insurance_summary"] == "In-network (Aetna) · Out-of-network"
    assert card["sliding_scale_label"] == "Yes"
    assert card["cost"] == "$220/session"


def test_affiliation_card_view_uses_explicit_org_when_passed():
    """``affiliation_card_view`` accepts an explicit ``org`` so the view-
    model isn't forced to read through ``affiliation.org`` — useful when
    the relationship hasn't been eager-loaded."""
    aff = _stub_affiliation(org=None, org_id="org-9")
    card = affiliation_card_view(aff, SimpleNamespace(name="Explicit Org"))
    assert card["org_name"] == "Explicit Org"
    assert card["org_url"] == "/organizations/org-9"


# --- provider_card_view.affiliations -------------------------------------


def test_view_returns_affiliations_list_one_per_row():
    """The detail page (#642 PR 2) renders one card per row in
    ``provider.affiliations``. The view-model exposes that as a list of
    per-affiliation dicts so the template loops a single list — no
    template-side dereferencing of ``affiliation.org.name``."""
    aff_a = _stub_affiliation(
        org_id="org-a",
        org=SimpleNamespace(name="Bedlam Health"),
        location_city="Brooklyn",
        sliding_scale=False,
        cost=None,
    )
    aff_b = _stub_affiliation(
        org_id="org-b",
        org=SimpleNamespace(name="Wellspring"),
        location_city="Queens",
        sliding_scale=True,
        cost="$220/session",
    )
    v = provider_card_view(_stub_provider(affiliations=[aff_a, aff_b]))
    assert isinstance(v["affiliations"], list)
    assert len(v["affiliations"]) == 2
    assert v["affiliations"][0]["org_name"] == "Bedlam Health"
    assert v["affiliations"][0]["org_url"] == "/organizations/org-a"
    assert v["affiliations"][0]["sliding_scale_label"] == "No"
    assert v["affiliations"][1]["org_name"] == "Wellspring"
    assert v["affiliations"][1]["org_url"] == "/organizations/org-b"
    assert v["affiliations"][1]["sliding_scale_label"] == "Yes"
    assert v["affiliations"][1]["cost"] == "$220/session"


def test_view_affiliations_is_empty_list_when_provider_has_none():
    """A Provider with zero affiliations (e.g. after every Affiliation
    was deleted via the inline list on the edit page — #642 PR 1)
    still returns a list, not ``None``, so the template's ``{% for %}``
    renders the empty case without an extra guard."""
    v = provider_card_view(_stub_provider(affiliations=[]))
    assert v["affiliations"] == []
