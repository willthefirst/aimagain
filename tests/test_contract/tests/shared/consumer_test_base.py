"""Base classes and utilities for consumer tests."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pact import Consumer
from playwright.async_api import Page

from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


class BaseConsumerTest(ABC):
    """Base class for consumer tests."""

    @property
    @abstractmethod
    def consumer_name(self) -> str:
        """The name of the consumer."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The name of the provider."""
        pass

    @property
    @abstractmethod
    def pact_port(self) -> int:
        """The port for the pact mock server."""
        pass

    @property
    @abstractmethod
    def api_path(self) -> str:
        """The API path being tested."""
        pass

    @property
    @abstractmethod
    def http_method(self) -> str:
        """The HTTP method being tested."""
        pass

    @property
    @abstractmethod
    def provider_state(self) -> str:
        """The provider state for the test."""
        pass

    @property
    @abstractmethod
    def expected_request_body(self) -> Dict[str, Any]:
        """The expected request body."""
        pass

    @property
    @abstractmethod
    def expected_request_headers(self) -> Dict[str, str]:
        """The expected request headers."""
        pass

    @property
    @abstractmethod
    def response_status(self) -> int:
        """The expected response status."""
        pass

    @property
    @abstractmethod
    def response_body(self) -> Optional[Dict[str, Any]]:
        """The expected response body."""
        pass

    @property
    def response_headers(self) -> Optional[Dict[str, str]]:
        """The expected response headers. Override if needed."""
        return {"Content-Type": "application/json"} if self.response_body else None

    def setup_pact_expectation(self, pact: Consumer):
        """Set up the pact expectation."""
        expectation = (
            pact.given(self.provider_state)
            .upon_receiving(f"a request to {self.api_path}")
            .with_request(
                method=self.http_method,
                path=self.api_path,
                headers=self.expected_request_headers,
                body=self.expected_request_body,
            )
        )

        response_config = {"status": self.response_status}
        if self.response_headers:
            response_config["headers"] = self.response_headers
        if self.response_body:
            response_config["body"] = self.response_body

        expectation.will_respond_with(**response_config)

    async def setup_playwright_interception(self, page: Page, mock_server_uri: str):
        """Set up Playwright interception."""
        mock_api_url = f"{mock_server_uri}{self.api_path}"
        await setup_playwright_pact_interception(
            page=page,
            api_path_to_intercept=self.api_path,
            mock_pact_url=mock_api_url,
            http_method=self.http_method,
        )

    def create_pact(self) -> Consumer:
        """Create and return a pact instance."""
        return setup_pact(self.consumer_name, self.provider_name, self.pact_port)

    @abstractmethod
    async def perform_user_actions(self, page: Page, origin: str):
        """Perform the user actions that trigger the API call."""
        pass

    async def run_test(self, origin: str, page: Page):
        """Standard test execution flow."""
        pact = self.create_pact()
        mock_server_uri = pact.uri

        self.setup_pact_expectation(pact)
        await self.setup_playwright_interception(page, mock_server_uri)

        with pact:
            await self.perform_user_actions(page, origin)
