"""Entity-specific facts for `CLINICIAN_ENTITY`.

Universal invariants (identity, audit-type, templates, `to_resource_spec()`
round-trip, etc.) live in `test_spec_conformance.py`. This file pins
what's unique to clinicians: list filters, the post-mutation redirects,
the auth_policy expansion, and the per-viewer extras binding.
"""

from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.framework.dispatch.entity_spec import AUTHENTICATED, OWNER_OR_ADMIN

# --- Auth deps + authorization (clinician-specific) -----------------------


def test_auth_deps_is_authenticated():
    """Clinicians expose CRUD to any active user; per-target write rules
    live in `auth_policy`."""
    assert CLINICIAN_ENTITY.auth_deps is AUTHENTICATED


def test_auth_policy_is_owner_or_admin():
    """Pinned identity of the sentinel. The pair-of-callables in
    `OWNER_OR_ADMIN` is the only `AuthzPolicy` instance that enforces
    "owner-or-admin"; a future refactor swapping it would silently
    change the mutation rule."""
    assert CLINICIAN_ENTITY.auth_policy is OWNER_OR_ADMIN


# --- List filters --------------------------------------------------------


def test_filters_are_owner_favorited_license_type_and_issuing_state():
    """`owner` and `favorited` are viewer-relative scope filters
    (`?owner=me` → viewer's own clinicians; `?favorited=me` → clinicians
    the viewer favorited — the replacement for the removed
    `/users/me/favorites` page). Both bypass the verified-only directory
    gate. The license filters are multi-select directory facets."""
    names = {f.name for f in CLINICIAN_ENTITY.filters}
    assert names == {"owner", "favorited", "license_type", "issuing_state"}


# --- Redirects -----------------------------------------------------------


def test_create_redirect_goes_to_homepage():
    """Post-create the user lands on `/`. NPPES verification now gates
    create, so a successful response means the clinician is already
    verified and there's no half-built row to nudge them into editing.
    See the comment on `_clinician_create_redirect` in
    `src/domain/specs/clinician.py`."""
    assert CLINICIAN_ENTITY.create_redirect(clinician_id="abc-123") == "/"


def test_update_redirect_stays_on_edit_form():
    assert (
        CLINICIAN_ENTITY.update_redirect(clinician_id="abc-123")
        == "/clinicians/abc-123/form"
    )


def test_delete_redirect_unset():
    """Clinician entries don't have a custom delete-redirect — the mount
    layer's default (`/clinicians`) handles it."""
    assert CLINICIAN_ENTITY.delete_redirect is None


# --- Extras binding ------------------------------------------------------


def test_detail_extras_path_points_at_clinician_detail_extras():
    """Pinning the dotted path so a callable rename surfaces here."""
    assert (
        CLINICIAN_ENTITY.detail_extras_path
        == "src.domain.logic.clinicians.handlers.clinician_detail_extras"
    )


# --- Static context (credential-type tuples + labels) -------------------


def test_static_context_carries_credential_enums():
    """Clinician templates render credential-type display labels and
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

    assert CLINICIAN_ENTITY.static_context == {
        "LICENSE_TYPES": LICENSE_TYPES,
        "LICENSE_TYPES_LABELS": LICENSE_TYPES_LABELS,
        "EDUCATION_TYPES": EDUCATION_TYPES,
        "EDUCATION_TYPES_LABELS": EDUCATION_TYPES_LABELS,
        "CERTIFICATION_TYPES": CERTIFICATION_TYPES,
        "CERTIFICATION_TYPES_LABELS": CERTIFICATION_TYPES_LABELS,
    }
