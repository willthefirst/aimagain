# Implementation Plan: Hybrid E2E + Pact Validation for HTMX/FastAPI

This plan outlines the steps to implement a testing strategy that uses End-to-End (E2E) tests on the frontend to capture HTMX form submissions and validates them against a Pact contract verified by the FastAPI backend.

**Assumptions:**

- Backend: FastAPI with Python tests (e.g., `pytest`, `httpx`).
- Frontend: Basic HTML with HTMX for form submissions (e.g., `<form hx-post="/auth/register">`).
- Goal: Ensure frontend/backend agreement on API interactions (e.g., `/auth/register` expects and receives `Content-Type: application/json`).
- Environment: Node.js available for frontend testing tools.

---

## Phase 1: Backend (Provider) - Defining and Verifying the Contract

_Goal: Ensure your FastAPI backend adheres to a defined contract for the target endpoint(s) and publish that contract._

1.  **Install Pact Python:**

    - Add `pact-python` to backend dependencies: `pip install pact-python` (or add to `requirements.txt`/`pyproject.toml`).

2.  **Configure Contract Storage:**

    - **Option A (Pact Broker - Recommended):** Set up a Pact Broker (local Docker/pactflow.io). Note its URL and credentials/token.
    - **Option B (Shared Files):** Designate a directory (e.g., `./pacts`) for contract files. Plan for sharing these files (e.g., CI artifacts).

3.  **Write Pact Provider Verification Test:**

    - Create a test file (e.g., `tests/test_pact_provider.py`).
    - Use `pytest` and `pact-python`.
    - **Configure `pact.Verifier`:**
      - `provider`: Name of your backend service (e.g., `'MyFastAPIProvider'`).
      - `provider_base_url`: URL for your running FastAPI test server (e.g., `http://localhost:8001`). This needs to be accessible during the test run (often managed via fixtures).
      - **Contract Source:**
        - Broker: `pact_broker_url`, `pact_broker_token` (or user/pass), `consumer_selectors`.
        - Files: `pact_files` (list of paths to `.json` contract files).
      - **(Optional) `provider_states_setup_url`:** If interactions require specific preconditions, define an endpoint on your test server that the Verifier can call to set up these states (e.g., database seeding/clearing).
      - **(Optional, Broker) `publish_verification_results=True`:** Report results back to the Broker.
    - **Run Verification:** Call `verifier.verify()` within a `pytest` test function. This fetches contracts, replays requests against your `provider_base_url`, and compares actual responses to contract expectations.

4.  **Integrate with Backend Test Suite & CI:**
    - Ensure the FastAPI test server is running when the Pact verification test executes.
    - Include the Pact test in your regular `pytest` run.
    - Configure CI to run `pytest`, ensuring the test server is available and Broker credentials (if used) are secure.

---

## Phase 2: Contract Sharing

_Goal: Make the verified contract available to the frontend test environment._

1.  **Pact Broker:** Automatically handled via publish/fetch mechanism.
2.  **Shared Files:**
    - Configure backend CI to archive the generated/verified `.json` pact file(s) from `./pacts` (or your chosen path).
    - Configure frontend CI to download this artifact into a known location (e.g., `./pacts`) before running frontend tests.

---

## Phase 3: Frontend (Consumer) - E2E Test & Contract Validation

_Goal: Run an E2E test that submits the HTMX form and validates the resulting HTTP request against the shared Pact contract._

1.  **Set up Frontend Test Environment:**

    - Ensure Node.js and npm/yarn are installed.
    - `npm init -y` (if no `package.json`).
    - Install dependencies:
      - `npm install --save-dev cypress` (or `playwright`)
      - `npm install --save-dev @pact-foundation/pact`

2.  **Configure E2E Framework (Example: Cypress):**

    - Run `npx cypress open` to scaffold files.

3.  **Write E2E Pact Validation Test:**

    - Create a test file (e.g., `cypress/e2e/auth.cy.js`).
    - **Import/Require Pact:** Use `@pact-foundation/pact` utilities.
    - **Load Pact Contract:**
      - In a `before` or `beforeEach` hook:
        - Fetch the contract JSON (from Broker via Pact JS utils, or read the shared file from `./pacts`).
        - Parse the JSON. Store the expected request details (method, path, headers, body structure) for the interaction under test (e.g., `POST /auth/register`).
    - **Write Test Case (`it` block):**
      - `cy.visit('/auth/register')`
      - `cy.intercept('POST', '/auth/register').as('registerRequest')`
      - Fill form fields: `cy.get(...).type(...)`
      - Submit form: `cy.get(...).click()`
      - `cy.wait('@registerRequest').then((interception) => { ... })`
    - **Inside `cy.wait().then()` callback:**
      - `const actualRequest = interception.request;`
      - Retrieve `expectedRequest` details from the loaded contract.
      - **Validate `actualRequest` against `expectedRequest`:**
        - `expect(actualRequest.method).to.equal(expectedRequest.method);`
        - Check path: `expect(actualRequest.path).to.equal(expectedRequest.path);`
        - Check headers: `expect(actualRequest.headers['content-type']).to.match(/application\/json/);` (or use Pact matching rules if more complex).
        - Check body: Parse `actualRequest.body` (if JSON expected by contract). Use Pact JS matching functions (e.g., `MatchersV3.like`) applied to the _expected_ body structure from the contract to validate the structure/types of the _actual_ body.
      - Fail the test if any assertion fails.

4.  **Integrate with Frontend Test Suite & CI:**
    - Add npm scripts for running E2E tests (e.g., `"test:e2e": "cypress run"`).
    - Configure CI:
      - Run _after_ backend tests and contract sharing.
      - Ensure the contract is accessible (download artifact / configure Broker access).
      - Execute the E2E tests.

---

## Workflow Summary

1.  **Backend Change:** Modify endpoint -> CI runs `pytest` -> Pact provider test verifies contract -> Publishes result/artifact.
2.  **Frontend Change:** Modify HTMX form -> CI runs E2E tests -> Test intercepts HTMX request -> Validates request against _existing_ contract -> Pass/Fail.
3.  **Contract Break:** Backend changes contract expectation -> Provider verification passes (new contract published) -> Frontend E2E test runs -> Fetches _new_ contract -> Validation fails until frontend is updated -> Test Fail.
