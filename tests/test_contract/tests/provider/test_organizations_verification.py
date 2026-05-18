"""Provider verification: every `organizations-api` pair in the manifest.

The route's `current_active_user` dependency is overridden by the
provider server fixture; `_handle_create_organization` is monkey-patched
out via the combined dependency config so this verification exercises
only the route layer.
"""

import pytest
from yarl import URL

from tests.test_contract.manifest import combined_handler_mocks, pairs_for_provider
from tests.test_contract.tests.shared.provider_verification_base import (
    create_provider_test_decorator,
    verify_pair,
)

_PROVIDER = "organizations-api"
_PAIRS = pairs_for_provider(_PROVIDER)
_DEPENDENCY_CONFIG = combined_handler_mocks(_PROVIDER)


@pytest.mark.provider
@pytest.mark.organizations
@create_provider_test_decorator(_DEPENDENCY_CONFIG, "with_organizations_api_mocks")
@pytest.mark.parametrize("pair", _PAIRS, ids=lambda p: p.consumer_name)
def test_provider_organizations_pact_verification(pair, provider_server: URL):
    """Verify every `organizations-api` Pact contract against the running provider server."""
    verify_pair(pair, provider_server)
