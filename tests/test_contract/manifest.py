"""Contract test pair registry. `KNOWN_PROVIDER_STATES` is derived from
`CONTRACT_PAIRS`; provider verification tests parametrize off it."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import pytest

from .infrastructure.servers.consumer import (
    _setup_clinician_create_form_stub,
    _setup_clinician_edit_form_stub,
    _setup_organization_create_form_stub,
    _setup_post_owner_actions_stub,
    _setup_program_create_form_stub,
    _setup_users_admin_actions_stub,
)
from .tests.shared.mock_data_factory import MockDataFactory


@dataclass(frozen=True)
class ContractPair:
    """One consumer-provider Pact pair.

    `consumer_name` and `provider_name` are the Pact participant names.
    `pact_port` is the per-pair mock-server port (must be unique).
    `handler_mocks_factory` returns a `{handler_path: {...}}` dict the
    provider server uses to monkey-patch business-logic handlers.
    `consumer_setup_fn` (optional) is the FastAPI route mounter for
    the consumer-server HTML stub when the pair drives a stubbed page.
    `provider_state` (optional) is the state string the consumer test's
    `pact.given(...)` uses; surfaced here so `KNOWN_PROVIDER_STATES`
    is derived rather than hand-maintained.
    `endpoints` is the static-analysis source of truth: the
    `("METHOD /path", ...)` tuples this pair covers. Read by
    `scripts/dev/contract_form_coverage_check.py` to verify every
    literal-URL form template has a corresponding pair. Forms whose
    submit URL is dynamic (macro-driven `hx-{{ method }}="{{ action }}"`)
    are skipped by the lint — they route through the entity dispatch
    layer that the existing entity-form pairs already cover.
    `pytest_marks` is the tuple of pytest marks applied to the
    parametrized provider verification (e.g. `pytest.mark.provider`,
    `pytest.mark.posts`).
    """

    consumer_name: str
    provider_name: str
    pact_port: int
    handler_mocks_factory: Optional[Callable[[], dict]] = None
    consumer_setup_fn: Optional[Callable] = None
    provider_state: Optional[str] = None
    endpoints: tuple = ()
    pytest_marks: tuple = ()


CONTRACT_PAIRS: list[ContractPair] = [
    ContractPair(
        consumer_name="registration-form",
        provider_name="auth-api",
        pact_port=1234,
        handler_mocks_factory=MockDataFactory.create_registration_dependency_config,
        consumer_setup_fn=None,  # uses real auth_pages router
        provider_state="User test.user@example.com does not exist",
        # Literal URL — `register.html` does `hx-post="/auth/register"`.
        # Picked up by `scripts/dev/contract_form_coverage_check.py` so
        # the form's URL never drifts away from a paired endpoint.
        endpoints=("POST /auth/register",),
        pytest_marks=(pytest.mark.provider, pytest.mark.auth),
    ),
    # `forgot-password-form` and `reset-password-form` differ from the
    # other auth-api pair: fastapi-users' `get_reset_password_router()`
    # routes call `BaseUserManager.{get_by_email,forgot_password,
    # reset_password}` directly — there is no local handler to patch.
    # The provider verification therefore mocks methods on our concrete
    # `src.auth_config.UserManager` (see the corresponding
    # `MockDataFactory.create_*_dependency_config` entries).
    ContractPair(
        consumer_name="forgot-password-form",
        provider_name="auth-api",
        pact_port=1243,
        handler_mocks_factory=MockDataFactory.create_forgot_password_dependency_config,
        consumer_setup_fn=None,  # uses real auth_pages router
        provider_state="User test.user@example.com can request a password reset",
        endpoints=("POST /auth/forgot-password",),
        pytest_marks=(pytest.mark.provider, pytest.mark.auth),
    ),
    ContractPair(
        consumer_name="reset-password-form",
        provider_name="auth-api",
        pact_port=1244,
        handler_mocks_factory=MockDataFactory.create_reset_password_dependency_config,
        consumer_setup_fn=None,  # uses real auth_pages router
        provider_state="Reset password token is valid for an active user",
        endpoints=("POST /auth/reset-password",),
        pytest_marks=(pytest.mark.provider, pytest.mark.auth),
    ),
    ContractPair(
        consumer_name="user-admin-actions",
        provider_name="users-api",
        pact_port=1235,
        handler_mocks_factory=MockDataFactory.create_user_activation_dependency_config,
        consumer_setup_fn=_setup_users_admin_actions_stub,
        provider_state="User 11111111-1111-1111-1111-111111111111 exists and is active",
        pytest_marks=(pytest.mark.provider, pytest.mark.users),
    ),
    ContractPair(
        consumer_name="post-owner-actions",
        provider_name="posts-api",
        pact_port=1238,
        handler_mocks_factory=MockDataFactory.create_post_delete_dependency_config,
        consumer_setup_fn=_setup_post_owner_actions_stub,
        provider_state="Post 22222222-2222-2222-2222-222222222222 exists and is owned by the requester",
        pytest_marks=(pytest.mark.provider, pytest.mark.posts),
    ),
    ContractPair(
        consumer_name="clinician-create-form",
        provider_name="clinicians-api",
        pact_port=1239,
        handler_mocks_factory=MockDataFactory.create_clinician_create_dependency_config,
        consumer_setup_fn=_setup_clinician_create_form_stub,
        provider_state="User can create a clinician",
        pytest_marks=(pytest.mark.provider, pytest.mark.clinicians),
    ),
    # `clinician-edit-form` covers the top-level `PATCH /clinicians/{id}`
    # form. After #642 PR 1 a Clinician may hold multiple Affiliations and
    # this form's per-role fields (`location_*`, sessions, insurance,
    # `sliding_scale`, `cost`) write through Clinician per-role property
    # proxies to the primary (oldest) affiliation row — the wire shape
    # is unchanged. The sub-resource POST / PATCH endpoints
    # `POST /clinicians/{id}/clinician_affiliations` and
    # `PATCH /clinicians/{id}/clinician_affiliations/{aff_id}` have their own
    # consumer UI (canonical-pattern conversion #1402; profile fields surfaced
    # in #1358 PR-f UI), but the wire round-trip is already covered by the
    # route tests in `src/domain/routes/test_clinicians.py`; adding a Pact
    # pair for them is deferred until a new HTTP client is involved.
    ContractPair(
        consumer_name="clinician-edit-form",
        provider_name="clinicians-api",
        pact_port=1240,
        handler_mocks_factory=MockDataFactory.create_clinician_update_dependency_config,
        consumer_setup_fn=_setup_clinician_edit_form_stub,
        provider_state="Clinician 44444444-4444-4444-4444-444444444444 exists and is owned by the requester",
        pytest_marks=(pytest.mark.provider, pytest.mark.clinicians),
    ),
    ContractPair(
        consumer_name="organization-create-form",
        provider_name="organizations-api",
        pact_port=1241,
        handler_mocks_factory=MockDataFactory.create_organization_create_dependency_config,
        consumer_setup_fn=_setup_organization_create_form_stub,
        provider_state="User can create an organization",
        pytest_marks=(pytest.mark.provider, pytest.mark.organizations),
    ),
    ContractPair(
        consumer_name="program-create-form",
        provider_name="programs-api",
        pact_port=1242,
        handler_mocks_factory=MockDataFactory.create_program_create_dependency_config,
        consumer_setup_fn=_setup_program_create_form_stub,
        provider_state="User can create a program",
        pytest_marks=(pytest.mark.provider, pytest.mark.programs),
    ),
]


def known_provider_states() -> list[str]:
    """Aggregate every pair's `provider_state` (deduplicated, in
    declaration order). Consumed by the `provider_server` fixture's
    state handler."""
    seen: set[str] = set()
    out: list[str] = []
    for pair in CONTRACT_PAIRS:
        if pair.provider_state and pair.provider_state not in seen:
            out.append(pair.provider_state)
            seen.add(pair.provider_state)
    return out


def pairs_for_provider(provider_name: str) -> list[ContractPair]:
    """All pairs whose `provider_name` matches. Provider verification
    tests parametrize over this list."""
    return [p for p in CONTRACT_PAIRS if p.provider_name == provider_name]


def combined_handler_mocks(provider_name: str) -> dict[str, Any]:
    """Merge every pair's handler-mocks dict for the given provider.

    The provider server is module-scoped — one server per provider — so
    every pair's handler mocks must be applied at module load. This
    helper produces the combined dict the parametrized verification
    test passes through `create_provider_test_decorator`.
    """
    combined: dict[str, Any] = {}
    for pair in pairs_for_provider(provider_name):
        if pair.handler_mocks_factory is not None:
            combined.update(pair.handler_mocks_factory())
    return combined
