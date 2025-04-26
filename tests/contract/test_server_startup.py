# tests/contract/test_server_startup.py
import pytest
import requests

# This test checks if the server fixture starts and can serve routes from the included router.


@pytest.mark.asyncio
async def test_server_fixture_starts_and_serves_auth_page(fastapi_server):
    """Test that the fastapi_server fixture initializes and serves the real /auth/register page."""
    assert isinstance(fastapi_server, str)
    assert fastapi_server.startswith("http://localhost:")
    print(f"FastAPI server fixture started successfully at: {fastapi_server}")

    # Request the actual application path served by the included router
    register_url = f"{fastapi_server}/auth/register"
    print(f"Attempting to reach {register_url}")

    try:
        response = requests.get(register_url, timeout=5)

        # Check if the server responded successfully (200 OK)
        # This confirms the router was included and the template was found/rendered
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        assert response.status_code == 200
        print(
            f"Successfully reached {register_url}, status code: {response.status_code}"
        )

        # Optionally, check for some expected content from the real template
        # This makes the test more robust against template rendering errors
        assert "<form" in response.text  # Check if a form tag is present
        assert "email" in response.text  # Check if the word email is present
        assert "password" in response.text  # Check if the word password is present
        print("Basic content check passed.")

    except requests.exceptions.RequestException as e:
        pytest.fail(
            f"Failed to connect to or get valid response from {register_url}: {e}"
        )
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during the test: {e}")


# You don't necessarily need the browser or pact fixtures for this specific test.
