"""Single source of truth for contract test pairs.

Each `ContractPair` registers a consumer-provider Pact pair with all its
scaffolding metadata. `KNOWN_PROVIDER_STATES` is derived from this list,
and the provider verification tests parametrize off it — replacing the
per-pair `BaseProviderVerification` subclasses that used to live in
`tests/provider/test_*_verification.py`.

Adding a contract pair requires:

1. An entry in `CONTRACT_PAIRS` here.
2. A consumer test under `tests/consumer/test_<pair>.py` that drives
   the form/partial with Playwright.
3. (Optionally) a per-pair `MockDataFactory.create_*_dependency_config`
   classmethod, referenced as `handler_mocks_factory`.
4. (If the consumer needs an HTML stub page that isn't already mounted)
   a `_setup_*_stub` function in `infrastructure/servers/consumer.py`,
   referenced as `consumer_setup_fn`.

Adding a pair does NOT require:

- editing the `KNOWN_PROVIDER_STATES` list — derived from this manifest.
- editing the `tests/provider/test_<resource>_verification.py` file —
  parametrized over `pairs_for_provider(...)`.

Removing a pair: delete the manifest entry, the consumer test file,
and any pair-specific bits in `MockDataFactory` / `consumer.py`. Nothing
else.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import pytest

from .infrastructure.servers.consumer import (
    _setup_post_owner_actions_stub,
    _setup_provider_profile_create_form_stub,
    _setup_provider_profile_edit_form_stub,
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
    pytest_marks: tuple = ()


CONTRACT_PAIRS: list[ContractPair] = [
    ContractPair(
        consumer_name="registration-form",
        provider_name="auth-api",
        pact_port=1234,
        handler_mocks_factory=MockDataFactory.create_registration_dependency_config,
        consumer_setup_fn=None,  # uses real auth_pages router
        provider_state="User test.user@example.com does not exist",
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
        consumer_name="provider-profile-create-form",
        provider_name="provider-profiles-api",
        pact_port=1239,
        handler_mocks_factory=MockDataFactory.create_provider_profile_create_dependency_config,
        consumer_setup_fn=_setup_provider_profile_create_form_stub,
        provider_state="User can create a provider profile",
        pytest_marks=(pytest.mark.provider, pytest.mark.providers),
    ),
    ContractPair(
        consumer_name="provider-profile-edit-form",
        provider_name="provider-profiles-api",
        pact_port=1240,
        handler_mocks_factory=MockDataFactory.create_provider_profile_update_dependency_config,
        consumer_setup_fn=_setup_provider_profile_edit_form_stub,
        provider_state="Provider profile 44444444-4444-4444-4444-444444444444 exists and is owned by the requester",
        pytest_marks=(pytest.mark.provider, pytest.mark.providers),
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
