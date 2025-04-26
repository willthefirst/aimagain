import pytest
import uvicorn
import time
import socket
import multiprocessing
import requests
from fastapi import FastAPI

# Remove HTMLResponse import as the router handles responses
# from fastapi.responses import HTMLResponse
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Ensure the app directory is in the Python path to import the router
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(PROJECT_ROOT))

# Import the specific router we need
from app.api.routes import auth_pages

# Ensure the templating engine is implicitly loaded via the router import
# from app.core.templating import templates # Might not be needed explicitly

# Remove static file path definitions as they are no longer needed
# STATIC_DIR = "static"
# REGISTER_HTML_PATH = os.path.join(STATIC_DIR, "auth", "register.html")


# --- Helper function to run the server ---
def run_server(host: str, port: int):
    """Target function to run uvicorn in a separate process."""
    # Need to create the app instance *inside* the new process
    # because FastAPI app instances are not easily pickleable
    app = FastAPI(title="Test Server Process")
    app.include_router(auth_pages.router)
    # Use a slightly less verbose log level for the server process
    uvicorn.run(app, host=host, port=port, log_level="info")


@pytest.fixture(scope="session")
def fastapi_server():
    """Pytest fixture to run the FastAPI app in a separate process."""
    # Find an available port dynamically
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("localhost", 0))
    port = s.getsockname()[1]
    host = "localhost"
    s.close()

    base_url = f"http://{host}:{port}"
    health_check_url = f"{base_url}/docs"  # Use /docs as a simple check

    # Create and start the server process
    server_process = multiprocessing.Process(
        target=run_server, args=(host, port), daemon=True
    )
    print(f"Starting server process on {base_url}...")
    server_process.start()

    # Wait for the server to be ready by polling a known endpoint
    max_wait = 10  # seconds
    start_time = time.time()
    server_ready = False
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(health_check_url, timeout=0.5)
            if response.status_code == 200:
                print("Server process responded to health check.")
                server_ready = True
                break
        except requests.exceptions.ConnectionError:
            pass  # Server not up yet
        except requests.exceptions.Timeout:
            pass  # Server might be starting but slow
        time.sleep(0.2)  # Wait before retrying

    if not server_ready:
        print("Server process failed to start within timeout.")
        server_process.terminate()
        server_process.join()
        pytest.fail(f"Server process did not become ready at {health_check_url}")

    yield base_url  # Provide the base URL to tests

    # Cleanup: Terminate the server process
    print(f"Terminating server process {base_url} (PID: {server_process.pid})...")
    server_process.terminate()
    server_process.join(timeout=5)  # Wait for termination
    if server_process.is_alive():
        print(
            f"Warning: Server process {server_process.pid} did not terminate gracefully, killing."
        )
        server_process.kill()
    print("Server process terminated.")


# --- Playwright Fixtures ---


@pytest.fixture(scope="session")  # Session scope for browser efficiency
async def browser():
    """Pytest fixture to launch a Playwright browser instance (headful)."""
    async with async_playwright() as p:
        # Launch headful browser (remove headless=False to run headless)
        print("Launching headful browser for testing...")
        browser = await p.chromium.launch(
            headless=False, slow_mo=50
        )  # slow_mo helps visualization
        yield browser
        print("Closing browser...")
        await browser.close()


@pytest.fixture(scope="function")  # Function scope for isolated pages
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()
