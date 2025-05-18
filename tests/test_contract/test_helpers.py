import atexit
import os
from typing import Generator

from pact import Consumer, Provider
from playwright.async_api import Page, Route

PACT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "pacts"))
PACT_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "log"))


def setup_pact(consumer_name: str, provider_name: str, port: int) -> Consumer:
    os.makedirs(PACT_LOG_DIR, exist_ok=True)

    pact = Consumer(consumer_name).has_pact_with(
        Provider(provider_name), pact_dir=PACT_DIR, log_dir=PACT_LOG_DIR, port=port
    )

    pact.start_service()
    atexit.register(pact.stop_service)
    return pact


async def setup_playwright_pact_interception(
    page: Page,  # playwright.async_api.Page
    api_path_to_intercept: str,
    mock_pact_url: str,
    http_method: str = "POST",  # Default to POST, can be overridden
):
    """Sets up Playwright to intercept requests to a given path and forward them to the Pact mock service."""

    async def handle_route(route: Route):  # playwright.async_api.Route
        # Check if the request method matches (case-insensitive for http_method)
        if (
            route.request.method.lower() == http_method.lower()
            and api_path_to_intercept in route.request.url
        ):
            # Log interception
            print(
                f"Intercepting {route.request.method} to {route.request.url}, forwarding to {mock_pact_url}"
            )

            # Forward to Pact mock service, removing content-length as it might be miscalculated by Playwright/Pact
            # when request body/url is changed.
            await route.continue_(
                url=mock_pact_url,  # Use the full URL to the pact mock service endpoint
                method=route.request.method,  # Preserve original method
                headers={
                    k: v
                    for k, v in route.request.headers.items()
                    if k.lower() != "content-length"
                },
                post_data=route.request.post_data,  # Preserve original post data if any
            )
        else:
            await route.continue_()

    await page.route(f"**{api_path_to_intercept}", handle_route)
