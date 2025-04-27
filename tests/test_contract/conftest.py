import pytest
import uvicorn
import time
import socket
import multiprocessing
import atexit  # Added for Pact cleanup
from fastapi import FastAPI
from playwright.async_api import async_playwright
from app.api.routes import auth_pages
from pact import Consumer, Provider  # Added for Pact

# Define Pact Consumer and Provider WITH CORRECT NAMES AND DIR
pact = Consumer(
    "frontend-pact",  # Match expected filename: frontend-pact-backend-api.json
).has_pact_with(
    Provider("backend-api"),  # Match expected filename and provider test config
    # pact_dir relative to project root (where pytest is likely run)
    pact_dir="pacts",
)


def run_server(host: str, port: int):
    """Target function to run uvicorn in a separate process."""
    app = FastAPI(title="Test Server Process")
    # Make sure the necessary routes for the test UI are included
    # If test_auth_forms loads /auth/register, it needs to be served
    app.include_router(auth_pages.router)
    # Add other routers if the test UI page depends on them

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _find_available_port() -> int:
    """Finds an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _start_server_process(host: str, port: int) -> multiprocessing.Process:
    """Starts the FastAPI server in a separate process."""
    server_process = multiprocessing.Process(
        target=run_server, args=(host, port), daemon=True
    )
    server_process.start()
    # Increased sleep time slightly to ensure server is ready
    time.sleep(1.5)
    return server_process


def _terminate_server_process(process: multiprocessing.Process, origin: str):
    """Terminates the server process."""
    if process.is_alive():
        print(f"Terminating server at {origin}...")
        process.terminate()
        process.join(timeout=5)  # Wait for termination
    if process.is_alive():
        print(f"Force terminating server at {origin}...")
        process.kill()  # Force kill if terminate didn't work
        process.join()
    print(f"Server at {origin} terminated.")


@pytest.fixture(scope="session")
def origin():
    """Pytest fixture to run the FastAPI app in a separate process."""
    host = "localhost"
    port = _find_available_port()
    origin_url = f"http://{host}:{port}"
    print(f"Starting test server at {origin_url}...")
    server_process = _start_server_process(host, port)
    # Check if server process started correctly
    if not server_process.is_alive():
        pytest.fail("Server process failed to start.", pytrace=False)
    print(f"Test server started at {origin_url}")

    yield origin_url

    print(f"Stopping test server at {origin_url}...")
    _terminate_server_process(server_process, origin_url)


@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance (headless by default)."""
    async with async_playwright() as p:
        # Consider launching headless for CI environments
        browser = await p.chromium.launch()  # Add headless=True if needed
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()


@pytest.fixture(scope="session")
def pact_mock():
    """Provides the configured Pact instance to tests."""
    try:
        pact.start_service()
        print("Pact mock server started on port", pact.port)
        yield pact
    finally:
        print("Stopping Pact mock server...")
        pact.stop_service()
        print("Pact mock server stopped.")
