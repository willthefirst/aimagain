"""Server management utilities for contract tests."""

import logging
import multiprocessing
import time
from typing import Callable, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI
from requests.exceptions import ConnectionError
from yarl import URL


def poll_server_ready(url: str, retries: int = 10, delay: float = 0.5) -> bool:
    """Polls a URL until it's responsive or retries are exhausted."""
    logger = logging.getLogger("server_management")

    for i in range(retries):
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                logger.info(f"Server at {url} is ready.")
                return True
        except ConnectionError:
            logger.debug(
                f"Server at {url} not ready yet (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        except requests.Timeout:
            logger.debug(
                f"Server at {url} timed out (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        time.sleep(delay)

    logger.error(f"Server at {url} failed to start after {retries} retries.")
    return False


def terminate_server_process(process: multiprocessing.Process) -> None:
    """Terminates the server process gracefully."""
    logger = logging.getLogger("server_management")

    process.terminate()
    process.join(timeout=3)

    if process.is_alive():
        logger.warning(
            f"Server process {process.pid} did not terminate gracefully. Killing."
        )
        process.kill()
        process.join(timeout=1)


def setup_health_check_route(app: FastAPI) -> None:
    """Adds a health check endpoint to the FastAPI app."""

    @app.get("/_health")
    async def health_check():
        return {"status": "ok"}


class ServerManager:
    """Base class for managing test servers."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.base_url = URL(f"http://{host}:{port}")
        self.process: Optional[multiprocessing.Process] = None
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    def start(self, target_function: Callable, *args, **kwargs) -> None:
        """Start the server process."""
        self.process = multiprocessing.Process(
            target=target_function,
            args=(self.host, self.port, *args),
            kwargs=kwargs,
            daemon=True,
        )
        self.process.start()

        health_check_url = f"{self.base_url}/_health"
        if not poll_server_ready(health_check_url, retries=20, delay=0.5):
            self.stop()
            raise RuntimeError(f"Server failed to start at {health_check_url}")

    def stop(self) -> None:
        """Stop the server process."""
        if self.process:
            terminate_server_process(self.process)
            self.process = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
