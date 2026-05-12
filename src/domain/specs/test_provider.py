"""Entity-specific facts for `PROVIDER_ENTITY`.

Universal invariants (identity, audit-type, templates, `to_resource_spec()`
round-trip, etc.) live in `test_spec_conformance.py`. This file pins
what's unique to providers: list filters, the post-mutation redirects,
the auth_policy expansion, and the per-viewer extras binding.
"""

from src.domain.specs.provider import PROVIDER_ENTITY
from src.framework.dispatch.entity_spec import AUTHENTICATED, OWNER_OR_ADMIN

# --- Auth deps + authorization (provider-specific) -----------------------


def test_auth_deps_is_authenticated():
    """Providers expose CRUD to any active user; per-target write rules
    live in `auth_policy`."""
    assert PROVIDER_ENTITY.auth_deps is AUTHENTICATED


def test_auth_policy_is_owner_or_admin():
    """Pinned identity of the sentinel. The pair-of-callables in
    `OWNER_OR_ADMIN` is the only `AuthzPolicy` instance that enforces
    "owner-or-admin"; a future refactor swapping it would silently
    change the mutation rule."""
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
        == "src.domain.logic.providers.handlers.provider_detail_extras"
    )


# --- Static context (credential-type tuples + labels) -------------------


def test_static_context_carries_credential_enums():
    """Provider templates render credential-type display labels and
    populate filter/select dropdowns from the matching tuples. Pinning
    the keys here means a rename in `enums.py` surfaces in tests
    before the page silently renders empty dropdowns."""
    from src.domain.models.enums import (
        CERTIFICATION_TYPES,
        CERTIFICATION_TYPES_LABELS,
        EDUCATION_TYPES,
        EDUCATION_TYPES_LABELS,
        LICENSE_TYPES,
        LICENSE_TYPES_LABELS,
    )

    assert PROVIDER_ENTITY.static_context == {
        "LICENSE_TYPES": LICENSE_TYPES,
        "LICENSE_TYPES_LABELS": LICENSE_TYPES_LABELS,
        "EDUCATION_TYPES": EDUCATION_TYPES,
        "EDUCATION_TYPES_LABELS": EDUCATION_TYPES_LABELS,
        "CERTIFICATION_TYPES": CERTIFICATION_TYPES,
        "CERTIFICATION_TYPES_LABELS": CERTIFICATION_TYPES_LABELS,
    }
