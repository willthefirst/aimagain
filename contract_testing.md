# Contract Testing for FastAPI HTML Forms with Playwright and Pact

This document outlines a strategy for creating consumer-driven contract tests that verify the interaction between real HTML forms rendered by a FastAPI application and the backend API endpoints they submit to. We use Playwright to simulate user interaction in a real browser and Pact to define and verify the HTTP contracts.

## Core Idea

The goal is to ensure that the data structure sent by a specific HTML form (when filled and submitted via a browser) exactly matches the format expected by the corresponding backend API endpoint, as defined in a Pact contract.

## Key Components

1.  **FastAPI Test Server**:

    - Runs the _actual_ FastAPI application within the test environment using `uvicorn`.
    - Its primary role in _consumer_ testing is to accurately render and serve the HTML pages containing the forms (e.g., using Jinja2 templates and `url_for`).
    - For simple page rendering that doesn't require database lookups, this server instance does _not_ need a separate test database configured.

2.  **Pact Mock Server (`pact-python`)**:

    - Acts as the stand-in for the real API during the consumer test.
    - Test setup defines the _expected_ HTTP request (method, path, headers, body) that the form submission should generate.
    - Test setup also defines the _expected_ HTTP response that the API should return upon receiving a valid request.
    - Listens for the request coming from the Playwright-driven browser.

3.  **Playwright**:

    - Launches a real browser instance to interact with the HTML form.
    - Navigates to the page served by the FastAPI Test Server.
    - Fills form fields and triggers submission, simulating user actions.
    - Uses request **interception** (`page.route`) to catch the form's HTTP submission _before_ it reaches the FastAPI Test Server's API endpoint handler.
    - **Redirects** the intercepted request to the Pact Mock Server for verification.

4.  **Pact Contract Verification**:
    - The Pact Mock Server compares the _actual_ HTTP request (received via Playwright redirection) against the _expected_ request defined in the test.
    - If they match, the consumer test passes, confirming the UI generates the correct request format.
    - A Pact contract file (`.pact`) is generated, capturing the verified interaction. This file is later used for Provider Verification against the actual API.

## Example Test Flow: Registration Form

Consider testing the `/auth/register` HTML form:

1.  **Setup**: Start the FastAPI Test Server and the Pact Mock Server. Define the Pact interaction for `POST /auth/register` (expecting `x-www-form-urlencoded` data with `email`, `username`, `password`) and the expected `201 Created` JSON response.
2.  **Navigate**: Playwright navigates the browser to `http://<fastapi_test_server_address>/auth/register`.
3.  **Intercept**: Playwright sets up interception to redirect any `POST` requests to `/auth/register` towards the Pact Mock Server's address (`http://localhost:1234/auth/register`).
4.  **Interact**: Playwright fills the `#email`, `#username`, and `#password` input fields in the form.
5.  **Submit**: Playwright clicks the "Register" button.
6.  **Verify**: The browser sends the form data. Playwright intercepts it and sends it to the Pact Mock Server. The Mock Server validates that the request matches the expected format defined in step 1. If valid, it returns the predefined `201` response back to the browser (via Playwright). The test calls `pact.verify()`.
7.  **Result**: If verification passes, a contract file is saved, proving the registration form correctly interacts with the expected API contract.

## How To Use Example Implementation (`tests/test_contract/test_auth_forms.py`)

1.  **Install Dependencies**:
    ```bash
    pip install fastapi uvicorn pytest pytest-asyncio playwright pact-python httpx sqlalchemy aiosqlite # Add others as needed
    ```
2.  **Initialize Playwright**:
    ```bash
    playwright install
    ```
3.  **Create Pact Directory**: Ensure a `./pacts` directory exists in your project root.
4.  **Run Tests**:
    ```bash
    pytest -v tests/test_contract/test_auth_forms.py
    ```

This approach provides strong confidence that your rendered HTML forms correctly integrate with your FastAPI backend according to the defined API contracts.
