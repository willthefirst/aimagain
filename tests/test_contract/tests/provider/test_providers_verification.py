"""Provider verification: every `providers-api` pair in the manifest.

The route's `current_active_user` dependency is overridden by the
provider server fixture; `handle_create_provider` is monkey-patched out
via the combined dependency config so this verification exercises only
the route layer.

One module-scoped provider server with all the mocks applied — every
pact file verifies against the same server.
"""

import pytest
from yarl import URL

from tests.test_contract.manifest import combined_handler_mocks, pairs_for_provider
from tests.test_contract.tests.shared.provider_verification_base import (
    create_provider_test_decorator,
    verify_pair,
)

_PROVIDER = "providers-api"
_PAIRS = pairs_for_provider(_PROVIDER)
_DEPENDENCY_CONFIG = combined_handler_mocks(_PROVIDER)


@pytest.mark.provider
@pytest.mark.providers
@create_provider_test_decorator(_DEPENDENCY_CONFIG, "with_providers_api_mocks")
@pytest.mark.parametrize("pair", _PAIRS, ids=lambda p: p.consumer_name)
def test_provider_providers_pact_verification(pair, provider_server: URL):
    """Verify every `providers-api` Pact contract against the running provider server."""
    verify_pair(pair, provider_server)
