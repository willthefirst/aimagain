"""Provider verification: every `auth-api` pair in the manifest.

The route's auth dependencies are overridden by the provider server
fixture; the registration handler is monkey-patched out via
`MockDataFactory.create_registration_dependency_config` so this
verification covers route shape only (the "waiter, not chef" split).
"""

import pytest
from yarl import URL

from tests.test_contract.manifest import combined_handler_mocks, pairs_for_provider
from tests.test_contract.tests.shared.provider_verification_base import (
    create_provider_test_decorator,
    verify_pair,
)

_PROVIDER = "auth-api"
_PAIRS = pairs_for_provider(_PROVIDER)
_DEPENDENCY_CONFIG = combined_handler_mocks(_PROVIDER)


@pytest.mark.provider
@pytest.mark.auth
@create_provider_test_decorator(_DEPENDENCY_CONFIG, "with_auth_api_mocks")
@pytest.mark.parametrize("pair", _PAIRS, ids=lambda p: p.consumer_name)
def test_provider_auth_pact_verification(pair, provider_server: URL):
    """Verify every `auth-api` Pact contract against the running provider server."""
    verify_pair(pair, provider_server)
