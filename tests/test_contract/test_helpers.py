import atexit
import os

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
    page: Page,
    api_path_to_intercept: str,
    mock_pact_url: str,
    http_method: str = "POST",
):
    """Sets up Playwright to intercept requests to a given path and forward them to the Pact mock service."""

    async def handle_route(route: Route):
        if (
            route.request.method.lower() == http_method.lower()
            and api_path_to_intercept in route.request.url
        ):
            print(
                f"Intercepting {route.request.method} to {route.request.url}, forwarding to {mock_pact_url}"
            )

            await route.continue_(
                url=mock_pact_url,
                method=route.request.method,
                headers={
                    k: v
                    for k, v in route.request.headers.items()
                    if k.lower() != "content-length"
                },
                post_data=route.request.post_data,
            )
        else:
            await route.continue_()

    await page.route(f"**{api_path_to_intercept}", handle_route)
