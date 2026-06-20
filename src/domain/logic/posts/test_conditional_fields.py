"""Conditional-required rules for referrals.

Pins the six rules in `REFERRAL_CONDITIONAL_RULES` end-to-end: a
triggered-but-empty payload 422s with the error located on the *dependent*
field (so `build_form_errors_dict` lands it on that form control), and the
non-triggered / satisfied cases pass. Partial-update sparseness is covered
too — a patch that omits a trigger field skips that rule.
"""

import pytest
from pydantic import ValidationError

from src.domain.logic.posts.schema import post_create_adapter, post_update_adapter
from src.framework.dispatch.mounts.create import build_form_errors_dict
from tests.helpers import referral_payload


def _create_errors(**overrides) -> dict[str, str]:
    """Validate a create payload expected to fail; return the
    field→message dict the form layer would render."""
    with pytest.raises(ValidationError) as ei:
        post_create_adapter.validate_python(referral_payload(**overrides))
    return build_form_errors_dict(ei.value.errors(), kind="referral")


# --- baseline -----------------------------------------------------------


def test_default_payload_is_valid():
    """The representative referral (in-person + city, in-network + carrier)
    satisfies every rule."""
    post_create_adapter.validate_python(referral_payload())


# --- in-person → city ---------------------------------------------------


def test_in_person_requires_city():
    errs = _create_errors(session_format=["in_person"], location_city=None)
    assert "location_city" in errs


def test_virtual_only_does_not_require_city():
    post_create_adapter.validate_python(
        referral_payload(session_format=["virtual"], location_city=None)
    )


def test_in_person_with_city_is_valid():
    post_create_adapter.validate_python(
        referral_payload(session_format=["in_person"], location_city="Oakland")
    )


# --- "Other" in a multi-select → its free text --------------------------


@pytest.mark.parametrize(
    "list_field,text_field",
    [
        ("services", "services_other_text"),
        ("languages", "languages_other_text"),
        ("pronouns", "pronouns_other_text"),
        ("insurance_carriers", "insurance_carriers_other_text"),
    ],
)
def test_other_token_requires_its_free_text(list_field, text_field):
    # `other` selected, free text blank → error lands on the text field.
    errs = _create_errors(**{list_field: ["other"], text_field: None})
    assert text_field in errs
    # ...and supplying the text clears it.
    post_create_adapter.validate_python(
        referral_payload(**{list_field: ["other"], text_field: "please specify"})
    )


# --- in-network → at least one carrier ----------------------------------


def test_in_network_requires_a_carrier():
    errs = _create_errors(accepts_in_network=True, insurance_carriers=[])
    assert "insurance_carriers" in errs


def test_not_in_network_allows_empty_carriers():
    post_create_adapter.validate_python(
        referral_payload(
            accepts_in_network=False, accepts_private_pay=True, insurance_carriers=[]
        )
    )


def test_in_network_other_carrier_needs_text_too():
    """`other` carrier satisfies the ≥1 rule but still needs its free text."""
    errs = _create_errors(
        accepts_in_network=True,
        insurance_carriers=["other"],
        insurance_carriers_other_text=None,
    )
    assert "insurance_carriers_other_text" in errs
    assert "insurance_carriers" not in errs  # the ≥1 rule is satisfied


# --- multiple violations surface together -------------------------------


def test_multiple_violations_each_target_their_field():
    errs = _create_errors(
        session_format=["in_person"],
        location_city=None,
        services=["other"],
        services_other_text=None,
    )
    assert {"location_city", "services_other_text"} <= set(errs)


# --- partial-update sparseness ------------------------------------------


def test_patch_without_trigger_field_skips_rule():
    """A patch that doesn't touch `session_format` doesn't fire the city
    rule, even though `location` is absent (left unchanged)."""
    post_update_adapter.validate_python({"kind": "referral", "description": "new"})


def test_patch_setting_in_person_without_city_is_rejected():
    """But if the patch *sets* in-person, it must carry a city."""
    with pytest.raises(ValidationError) as ei:
        post_update_adapter.validate_python(
            {"kind": "referral", "session_format": ["in_person"]}
        )
    assert build_form_errors_dict(ei.value.errors(), kind="referral").get(
        "location_city"
    )
