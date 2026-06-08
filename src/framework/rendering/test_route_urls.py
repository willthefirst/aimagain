"""Tests for ``entity_url`` and ``entity_form_url``.

The helpers read from the live :data:`entity_registry`, populated at
import time by every entity route file under ``src/domain/routes/``.
Importing ``src.main`` or any route file is enough to populate the
registry — these tests rely on the conftest's app import chain.
"""

import uuid

import pytest

from src.domain.logic import capabilities
from src.framework.rendering.route_urls import (
    entity_form_url,
    entity_lock_reason,
    entity_url,
)

# --- entity_url --------------------------------------------------------


def test_entity_url_collection_path_for_organization():
    assert entity_url("organization") == "/organizations"


def test_entity_url_collection_path_for_program():
    assert entity_url("program") == "/programs"


def test_entity_url_collection_path_for_clinician():
    assert entity_url("clinician") == "/clinicians"


def test_entity_url_collection_path_for_post():
    """`/posts` is the whole-supertype face listing every kind
    (`referral`, `clinician_opening`, `program_intake`). Entity name
    stays singular ("post" — the umbrella concept) following the
    user/users naming convention."""
    assert entity_url("post") == "/posts"


def test_no_per_kind_entity_names():
    """Per-kind URL families (`/referrals`, `/openings`, `/intakes`)
    were folded into the single `/posts` face — `referral`, `opening`,
    and `intake` are not entity names. Verifies the consolidation is
    complete."""
    for stale_name in ("referral", "opening", "intake"):
        with pytest.raises(ValueError, match="Unknown entity name"):
            entity_url(stale_name)


def test_entity_url_collection_path_for_user():
    assert entity_url("user") == "/users"


def test_entity_url_item_path_with_uuid():
    org_id = uuid.UUID("88888888-8888-8888-8888-888888888888")
    assert entity_url("organization", id=org_id) == f"/organizations/{org_id}"


def test_entity_url_item_path_with_string_id():
    assert entity_url("user", id="me") == "/users/me"


def test_entity_url_uses_prefix_override_for_favorites():
    """``UserFavorite`` declares ``prefix_override="/users/me/favorites"`` —
    the helper must use it, not ``/favorites``."""
    assert entity_url("user_favorite") == "/users/me/favorites"


def test_entity_url_item_path_under_prefix_override():
    item_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    assert entity_url("user_favorite", id=item_id) == f"/users/me/favorites/{item_id}"


def test_entity_url_with_subresource():
    """State-axis subresources like ``/users/{id}/activation`` (per
    `RESOURCE_GRAMMAR.md`) round-trip through the helper."""
    uid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert (
        entity_url("user", id=uid, subresource="activation")
        == f"/users/{uid}/activation"
    )


def test_entity_url_subresource_without_id_raises():
    with pytest.raises(ValueError) as exc:
        entity_url("user", subresource="activation")
    assert "subresource" in str(exc.value)


def test_entity_url_unknown_entity_raises():
    """Typoed names fail loudly so the error surfaces at template render
    time rather than producing a 404-causing path."""
    with pytest.raises(ValueError) as exc:
        entity_url("organizations")  # plural — common typo
    assert "Unknown entity" in str(exc.value)
    assert "organization" in str(exc.value)  # the singular IS registered


# --- entity_form_url ---------------------------------------------------


def test_entity_form_url_create_form_for_organization():
    assert entity_form_url("organization") == "/organizations/form"


def test_entity_form_url_edit_form_for_organization():
    org_id = uuid.UUID("88888888-8888-8888-8888-888888888888")
    assert entity_form_url("organization", id=org_id) == f"/organizations/{org_id}/form"


def test_entity_form_url_create_form_for_program():
    assert entity_form_url("program") == "/programs/form"


def test_entity_form_url_create_form_for_clinician():
    assert entity_form_url("clinician") == "/clinicians/form"


def test_entity_form_url_create_form_for_post():
    """`/posts/form` is the create-form URL; the handler reads
    `?kind=X` from the query string to dispatch to the kind-specific
    form template (or renders the picker when no kind is supplied)."""
    assert entity_form_url("post") == "/posts/form"


def test_entity_form_url_edit_form_for_user():
    uid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert entity_form_url("user", id=uid) == f"/users/{uid}/form"


def test_entity_form_url_unknown_entity_raises():
    with pytest.raises(ValueError):
        entity_form_url("clinician_licensure_typo")


# --- entity_lock_reason ------------------------------------------------


class _Unverified:
    """Stand-in viewer that fails `can_access_network` — email unverified
    short-circuits the predicate, no need to construct a real ORM user."""

    is_verified = False
    is_superuser = False
    clinicians = ()
    org_representations = ()


class _Verified:
    """Stand-in viewer with a verified clinician profile — passes the
    network gate without constructing a real ORM user."""

    is_verified = True
    is_superuser = False
    org_representations = ()

    class _Cln:
        clinician_verified = True

    clinicians = (_Cln(),)


def test_entity_lock_reason_returns_reason_when_viewer_locked_out():
    """`user`'s spec declares `lock_reason=REASON_NETWORK_UNVERIFIED`;
    an unverified viewer fails `can_access_network`, so the helper hands
    back the reason code so `entity_link` can render a popover trigger."""
    assert (
        entity_lock_reason("user", _Unverified())
        == capabilities.REASON_NETWORK_UNVERIFIED
    )


def test_entity_lock_reason_none_when_viewer_passes_gate():
    """A network-verified viewer passes `can_read` — the helper returns
    `None` so `entity_link` renders the plain `<a>` branch."""
    assert entity_lock_reason("user", _Verified()) is None


def test_entity_lock_reason_none_for_entity_without_read_policy():
    """`organization` declares no `read_policy` — listing is open, so
    there's no lock affordance to render regardless of viewer."""
    assert entity_lock_reason("organization", _Unverified()) is None


def test_entity_lock_reason_unknown_entity_raises():
    """Same fail-loud contract as `entity_url` — typo in a template
    name surfaces as a render-time error rather than a silent bypass."""
    with pytest.raises(ValueError, match="Unknown entity name"):
        entity_lock_reason("clinician_licensure_typo", _Unverified())
