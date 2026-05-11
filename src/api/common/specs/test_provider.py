"""Entity-specific facts for `PROVIDER_ENTITY`.

Universal invariants (identity, audit-type, templates, `to_resource_spec()`
round-trip, etc.) live in `test_spec_conformance.py`. This file pins
what's unique to providers: list filters, the post-mutation redirects,
the auth_policy expansion, and the per-viewer extras binding.
"""

from src.api.common.entity_spec import OWNER_OR_ADMIN
from src.api.common.specs.provider import PROVIDER_ENTITY

# --- Authorization (provider-specific) -----------------------------------


def test_auth_policy_is_owner_or_admin():
    """Pinned identity of the sentinel — `OWNER_OR_ADMIN` is the
    `AuthzPolicy(assert_owner_or_admin, is_owner_or_admin)` pair and
    a future spec mistakenly setting `auth_policy=AUTHENTICATED` (when
    AuthDeps lands) would silently widen mutation access."""
    assert PROVIDER_ENTITY.auth_policy is OWNER_OR_ADMIN


# --- List filters --------------------------------------------------------


def test_filters_are_license_type_and_issuing_state():
    names = {f.name for f in PROVIDER_ENTITY.filters}
    assert names == {"license_type", "issuing_state"}


# --- Redirects -----------------------------------------------------------


def test_create_and_update_redirect_to_edit_form():
    target = "/providers/abc-123/form"
    assert PROVIDER_ENTITY.create_redirect(provider_id="abc-123") == target
    assert PROVIDER_ENTITY.update_redirect(provider_id="abc-123") == target


def test_delete_redirect_unset():
    """Providers don't have a custom delete-redirect — the mount layer's
    default (`/providers`) handles it."""
    assert PROVIDER_ENTITY.delete_redirect is None


# --- Extras binding ------------------------------------------------------


def test_detail_extras_path_points_at_provider_detail_extras():
    """Pinning the dotted path so a callable rename surfaces here."""
    assert (
        PROVIDER_ENTITY.detail_extras_path
        == "src.logic.providers.provider_processing.provider_detail_extras"
    )
