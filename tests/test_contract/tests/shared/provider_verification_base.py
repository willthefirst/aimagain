"""Base classes and utilities for provider verification tests."""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict

import pytest
from pact import Verifier
from yarl import URL

from tests.test_contract.infrastructure.config import PROVIDER_STATE_SETUP_FULL_URL
from tests.test_contract.tests.shared.helpers import PACT_DIR, PACT_LOG_DIR

log = logging.getLogger(__name__)


def verify_pact_and_handle_result(success: int, logs_dict: dict, pact_name: str):
    """Helper function to handle pact verification results."""
    if success != 0:
        log.error(f"{pact_name} Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        except Exception as e:
            log.error(f"Error printing pact logs: {e}")
            print(logs_dict)
        pytest.fail(
            f"{pact_name} Pact verification failed (exit code: {success}). Check logs."
        )


class BaseProviderVerification(ABC):
    """Base class for provider verification tests."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The name of the provider being verified."""
        pass

    @property
    @abstractmethod
    def consumer_name(self) -> str:
        """The name of the consumer that generated the pact."""
        pass

    @property
    @abstractmethod
    def dependency_config(self) -> Dict[str, Any]:
        """The dependency configuration for mocking."""
        pass

    @property
    @abstractmethod
    def pytest_marks(self) -> list:
        """List of pytest marks to apply to the test."""
        pass

    @property
    def pact_file_path(self) -> str:
        """Generate the pact file path based on consumer and provider names."""
        return os.path.join(PACT_DIR, f"{self.consumer_name}-{self.provider_name}.json")

    def verify_pact(self, provider_server: URL):
        """Standard pact verification logic."""
        if not os.path.exists(self.pact_file_path):
            pytest.fail(
                f"Pact file not found: {self.pact_file_path}. Run consumer test first."
            )

        verifier = Verifier(
            provider=self.provider_name,
            provider_base_url=str(provider_server),
            provider_states_setup_url=PROVIDER_STATE_SETUP_FULL_URL,
        )

        success, logs_dict = verifier.verify_pacts(
            self.pact_file_path, log_dir=PACT_LOG_DIR
        )

        verify_pact_and_handle_result(
            success, logs_dict, f"{self.provider_name.title()} API"
        )


def create_provider_test_decorator(dependency_config: Dict[str, Any], test_id: str):
    """Create a parametrize decorator for provider tests."""
    return pytest.mark.parametrize(
        "provider_server",
        [dependency_config],
        indirect=True,
        scope="module",
        ids=[test_id],
    )
