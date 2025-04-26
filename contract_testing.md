# Contract Testing Strategy: FastAPI UI (Playwright) + API (Pact)

This document outlines the plan for creating consumer-driven contract tests for the FastAPI application, focusing initially on the user registration flow. The goal is to verify that the interactions initiated from the user interface (simulated by Playwright) conform to the API contracts defined and verified by Pact.

## Core Idea

We aim to ensure that the data structure sent by specific HTML forms (when filled and submitted via a browser) matches the format expected by the corresponding backend API endpoint, as defined in a Pact contract. We will use pre-generated static HTML files served by a minimal test server to isolate the UI interaction for testing.

## Plan for Registration Form (`/auth/register`)

1.  **Target Flow**:

    - User accesses the registration page (`GET /auth/register`).
    - User fills in the registration form (email, password, etc.).
    - User submits the form, triggering a `POST /auth/register` request.

2.  **Key Components**:

    - **Static HTML**: Pre-generate `static/auth/register.html` using the application's Jinja templating (`app/core/templating.py`, template `auth/register.html`).
    - **Minimal FastAPI Test Server**: A simple server (similar to `contrac_testing_example.py`) will serve the generated `static/auth/register.html` at a specific test route (e.g., `/test/register`). This server does _not_ need to connect to the full backend or database for this consumer test.
    - **Pact Mock Server (`pact-python`)**:
      - Define the _expected_ HTTP request for `POST /auth/register` (method, path, headers, body format - likely `application/x-www-form-urlencoded`).
      - Define the _expected_ HTTP response (e.g., `200 OK` or `201 Created` with specific JSON body).
      - Listen for the request redirected from Playwright.
    - **Playwright**:
      - Launch a browser instance.
      - Navigate to the test server's registration page (`/test/register`).
      - Fill the form fields.
      - **Intercept** the `POST /auth/register` request triggered by the form submission.
      - **Redirect** the intercepted request to the Pact Mock Server (`http://localhost:1234/auth/register`).
    - **Pact Verification**:
      - The Pact Mock Server compares the _actual_ request received from Playwright against the _expected_ request.
      - If they match, the consumer test passes, and a Pact contract file (`.pact`) is generated.

3.  **Implementation Steps**:

    - **A: Understand Jinja Setup**: Examine `app/core/templating.py` to see how the Jinja environment is configured (needed for static generation).
    - **B: Static HTML Generation Function**: Create a Python function (e.g., `create_register_html()`) that uses the Jinja environment to render `auth/register.html` into `static/auth/register.html`. This function should be run before tests.
    - **C: Test Server Fixture**: Adapt the `fastapi_server` fixture to serve the static `static/auth/register.html` file at `/test/register`.
    - **D: Playwright/Pact Test**: Create the `test_registration_form_submission` async test function:
      - Set up the `pact_mock` fixture.
      - Define the expected `POST /auth/register` interaction in Pact.
      - Implement Playwright `page.route` for interception/redirection.
      - Add Playwright commands to navigate, fill the form (using correct element IDs/names from the template), and click submit.
      - Call `pact_mock.verify()`.

4.  **Next Steps (After Consumer Test)**:
    - Use the generated `.pact` file to run a **Provider Verification** test against the _real_ FastAPI application (`app/main.py`) to ensure the actual `POST /auth/register` endpoint fulfills the contract. This will likely involve setting up provider states if needed (e.g., ensuring a user doesn't already exist).

## Test File Structure (Example)

```
tests/
├── contract/
│   ├── __init__.py
│   ├── test_auth_forms.py  # Contains the consumer test
│   └── provider/           # Directory for provider verification tests
│       └── __init__.py
│       └── test_auth_provider.py
├── conftest.py             # Fixtures (fastapi_server, pact_mock, page)
static/                     # Generated static files for tests
│   └── auth/
│       └── register.html
pacts/                      # Generated pact files
└── profilepageui-profileapi.json # Example pact file
```

This plan focuses on creating a robust consumer test for the registration UI, ensuring it sends data in the correct format before moving on to provider verification.
