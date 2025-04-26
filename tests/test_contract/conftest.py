import pytest
import uvicorn
import time
import socket
import multiprocessing
from fastapi import FastAPI
from playwright.async_api import async_playwright
from app.api.routes import auth_pages


def run_server(host: str, port: int):
    """Target function to run uvicorn in a separate process."""
    app = FastAPI(title="Test Server Process")
    app.include_router(auth_pages.router)

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
    time.sleep(1)
    return server_process


def _terminate_server_process(process: multiprocessing.Process, origin: str):
    """Terminates the server process."""
    process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        process.kill()


@pytest.fixture(scope="session")
def origin():
    """Pytest fixture to run the FastAPI app in a separate process."""
    host = "localhost"
    port = _find_available_port()
    origin = f"http://{host}:{port}"

    server_process = _start_server_process(host, port)

    yield origin

    _terminate_server_process(server_process, origin)


@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance (headful)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()
