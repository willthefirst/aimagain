"""Tests for the provider view helpers (`view.py`)."""

from types import SimpleNamespace

from src.domain.logic.providers.view import (
    _full_address,
    _insurance_summary,
    provider_card_view,
)


def _stub_provider(**overrides):
    """Realistic Provider stub. Defaults populate every field with a
    sensible value so tests can override only what they care about.

    `npi` lives on the linked ``Clinician`` after #629 PR 1 — the view
    reads ``provider.clinician.npi``. Tests still pass `npi=...` for
    ergonomics; the stub builder rolls the kwarg into a nested
    ``clinician`` SimpleNamespace so the view sees the same shape it
    sees in production.
    """
    npi = overrides.pop("npi", None)
    defaults = dict(
        org_id="org-1",
        org=SimpleNamespace(name="Acme Counseling"),
        clinician=SimpleNamespace(npi=npi),
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
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --- _full_address -----------------------------------------------------


def test_full_address_composes_all_three_parts():
    assert _full_address("Brooklyn", "NY", "11201") == "Brooklyn, NY 11201"


def test_full_address_handles_missing_zip():
    assert _full_address("Brooklyn", "NY", None) == "Brooklyn, NY"


def test_full_address_handles_missing_city():
    assert _full_address(None, "NY", "11201") == "NY 11201"


def test_full_address_returns_none_when_all_empty():
    assert _full_address(None, None, None) is None
    assert _full_address("", "", "") is None


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
