"""Tests for `src/framework/http/responses.py` helpers."""

import json
import uuid
from types import SimpleNamespace

import pytest

from .responses import (
    base_context,
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)

# --- base_context: chrome scalars ----------------------------------------


def test_base_context_anonymous():
    ctx = base_context(None)
    assert ctx == {
        "is_authenticated": False,
        "is_admin": False,
        "current_username": None,
        "current_user_id": None,
        "has_clinician_profile": False,
        # Anonymous users don't get the verify nag — default True so
        # the banner stays silent.
        "current_user_is_verified": True,
        # Claim-aware chrome (claim-based verification rollout) — anon
        # holds no claims and has no lapsed claims.
        "claims": {"a": False, "b": []},
        "claim_a_lapsed": False,
        "claim_b_lapsed_orgs": [],
        "any_claim_lapsed": False,
        "can_read_full_feed": False,
        "can_post": False,
        # Anonymous viewers never see the incomplete-profile banner; the
        # checklist is only computed for an authed user.
        "onboarding_incomplete": False,
        "onboarding_next_href": "/profile",
    }


def test_base_context_regular_user():
    user_id = uuid.uuid4()
    user = SimpleNamespace(
        id=user_id, username="alice", is_superuser=False, is_verified=True
    )
    assert base_context(user) == {
        "is_authenticated": True,
        "is_admin": False,
        "current_username": "alice",
        "current_user_id": user_id,
        "has_clinician_profile": False,
        "current_user_is_verified": True,
        # No clinicians on this stub → Claim A is False; OrgRepresentation
        # placeholders keep `b` empty.
        "claims": {"a": False, "b": []},
        "claim_a_lapsed": False,
        "claim_b_lapsed_orgs": [],
        "any_claim_lapsed": False,
        "can_read_full_feed": False,
        "can_post": False,
        # Email verified but no claim → identity step incomplete, so the
        # banner shows and points at the claim-A focus deep-link.
        "onboarding_incomplete": True,
        "onboarding_next_href": "/profile?focus=claim_a",
    }


def test_base_context_claim_a_verified_user():
    """A user with a `clinician_verified=True` cache on at least one
    `Clinician` flips `claims.a` to True. Pins the wiring between
    `base_context()` and `capabilities.claim_state()` — Phase 5's
    profile-hub mode dispatcher reads this same shape."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="alice",
        is_superuser=False,
        is_verified=True,
        clinicians=[
            SimpleNamespace(
                npi="1234567890",
                clinician_verified=True,
                ever_verified_at=None,
            )
        ],
        org_representations=[],
    )
    ctx = base_context(user)
    assert ctx["claims"] == {"a": True, "b": []}
    assert ctx["any_claim_lapsed"] is False


def test_base_context_can_read_full_feed_true_for_verified_clinician():
    """The chrome scalar `can_read_full_feed` powers `home.html`'s
    network-feed blur — pinned here so a regression in `base_context`
    can't silently re-blur every authed user's feed."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="bob",
        is_superuser=False,
        is_verified=True,
        clinicians=[
            SimpleNamespace(
                npi="1234567890", clinician_verified=True, ever_verified_at=None
            )
        ],
        org_representations=[],
    )
    assert base_context(user)["can_read_full_feed"] is True


def test_base_context_claim_b_coordinator():
    """A program coordinator (no clinician profile) with a verified
    OrgRepresentation gets `claims.b` populated with the org id."""
    org_id = uuid.uuid4()
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="dana",
        is_superuser=False,
        is_verified=True,
        clinicians=[],
        org_representations=[
            SimpleNamespace(
                org_id=org_id,
                authority_status="verified",
                archived_at=None,
            )
        ],
    )
    ctx = base_context(user)
    assert ctx["claims"]["a"] is False
    assert ctx["claims"]["b"] == [org_id]


def test_base_context_can_post_true_for_claim_a():
    """`can_post` is True when Claim A is held — Claim A users see the chrome post CTA."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="alice",
        is_superuser=False,
        is_verified=True,
        clinicians=[
            SimpleNamespace(
                npi="1234567890", clinician_verified=True, ever_verified_at=None
            )
        ],
        org_representations=[],
    )
    assert base_context(user)["can_post"] is True


def test_base_context_can_post_false_for_claim_b_only():
    """`can_post` is False when only Claim B is held — org reps have no chrome post CTA.
    The server (`_assert_post_payload_authz`) still authorizes them; the chrome
    is deliberately narrower."""
    org_id = uuid.uuid4()
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="dana",
        is_superuser=False,
        is_verified=True,
        clinicians=[],
        org_representations=[
            SimpleNamespace(
                org_id=org_id, authority_status="verified", archived_at=None
            )
        ],
    )
    ctx = base_context(user)
    assert ctx["can_post"] is False
    assert ctx["claims"]["b"] == [org_id]


def test_base_context_onboarding_complete_silences_banner():
    """A verified clinician has cleared the spine, so `onboarding_incomplete`
    is False and the global banner stays silent."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="alice",
        is_superuser=False,
        is_verified=True,
        clinicians=[
            SimpleNamespace(
                npi="1234567890", clinician_verified=True, ever_verified_at=None
            )
        ],
        org_representations=[],
    )
    ctx = base_context(user)
    assert ctx["onboarding_incomplete"] is False


def test_base_context_unverified_email_points_banner_at_email():
    """An unverified-email user's first incomplete step is email, so the
    banner deep-links to the email focus."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="alice",
        is_superuser=False,
        is_verified=False,
        clinicians=[],
        org_representations=[],
    )
    ctx = base_context(user)
    assert ctx["onboarding_incomplete"] is True
    assert ctx["onboarding_next_href"] == "/profile?focus=email"


def test_base_context_unverified_user_surfaces_for_nag_banner():
    """A user with `is_verified=False` is what triggers the nag
    banner in `_verify_banner.html`. Pin the scalar's exact shape."""
    user = SimpleNamespace(
        id=uuid.uuid4(), username="alice", is_superuser=False, is_verified=False
    )
    assert base_context(user)["current_user_is_verified"] is False


def test_base_context_user_without_is_verified_attr_defaults_true():
    """`Actor` doesn't declare `is_verified`; test stubs lacking the
    attribute must not accidentally raise the banner. Default True
    keeps the nag opt-in (only real `is_verified=False` rows show)."""
    user = SimpleNamespace(id=uuid.uuid4(), username="alice", is_superuser=False)
    assert base_context(user)["current_user_is_verified"] is True


def test_base_context_admin():
    user = SimpleNamespace(id=uuid.uuid4(), username="root", is_superuser=True)
    ctx = base_context(user)
    assert ctx["is_admin"] is True
    assert ctx["is_authenticated"] is True


def test_base_context_user_with_clinician_profile():
    """A user whose `clinicians` relationship is non-empty reads as
    `has_clinician_profile=True` — the chrome uses this to swap the
    primary CTA from "Set up your profile" to "+ Post availability"."""
    user = SimpleNamespace(
        id=uuid.uuid4(),
        username="alice",
        is_superuser=False,
        clinicians=[SimpleNamespace(id=uuid.uuid4())],
    )
    ctx = base_context(user)
    assert ctx["has_clinician_profile"] is True


def test_base_context_user_without_clinicians_attr_defaults_false():
    """Missing `clinicians` attribute (Actor protocol doesn't declare it)
    defaults to `False` — same shape as a brand-new user who hasn't
    created a clinician profile yet."""
    user = SimpleNamespace(id=uuid.uuid4(), username="alice", is_superuser=False)
    assert base_context(user)["has_clinician_profile"] is False


# --- existing helpers ----------------------------------------------------


def test_created_response_defaults_hx_redirect_to_location():
    obj_id = uuid.uuid4()
    resp = created_response(id=obj_id, location=f"/posts/{obj_id}")
    assert resp.status_code == 201
    assert json.loads(resp.body) == {"id": str(obj_id)}
    assert resp.headers["Location"] == f"/posts/{obj_id}"
    assert resp.headers["HX-Redirect"] == f"/posts/{obj_id}"


def test_created_response_separate_location_and_hx_redirect():
    obj_id = uuid.uuid4()
    resp = created_response(
        id=obj_id,
        location=f"/clinicians/{obj_id}",
        hx_redirect=f"/clinicians/{obj_id}/form",
    )
    assert resp.headers["Location"] == f"/clinicians/{obj_id}"
    assert resp.headers["HX-Redirect"] == f"/clinicians/{obj_id}/form"


def test_updated_response_with_body():
    resp = updated_response(body={"id": "abc", "name": "x"}, hx_redirect="/x")
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"id": "abc", "name": "x"}
    assert resp.headers["HX-Redirect"] == "/x"


def test_updated_response_empty_body_default():
    resp = updated_response(hx_redirect="/x")
    assert resp.status_code == 200
    assert json.loads(resp.body) == {}


def test_deleted_response_204_with_hx_redirect():
    resp = deleted_response(hx_redirect="/posts")
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/posts"


def test_refreshed_response_204_with_hx_refresh():
    resp = refreshed_response()
    assert resp.status_code == 200
    assert resp.headers["HX-Refresh"] == "true"


def test_updated_response_hx_refresh_sets_header_with_body():
    """`hx_refresh=True` swaps the HX-Redirect header for HX-Refresh while
    keeping the optional body — the shape state-axis subresources need."""
    resp = updated_response(body={"id": "u1", "is_active": False}, hx_refresh=True)
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"id": "u1", "is_active": False}
    assert resp.headers["HX-Refresh"] == "true"
    assert "HX-Redirect" not in resp.headers


def test_updated_response_requires_one_of_redirect_or_refresh():
    with pytest.raises(ValueError, match="hx_redirect or hx_refresh"):
        updated_response(body={"x": 1})


def test_updated_response_rejects_both_redirect_and_refresh():
    with pytest.raises(ValueError, match="hx_redirect or hx_refresh"):
        updated_response(hx_redirect="/x", hx_refresh=True)
