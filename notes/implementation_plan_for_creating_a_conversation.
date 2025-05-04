
Okay, let's integrate the TDD workflow explicitly into each step, emphasizing the use of `pytest` to ensure continuous integration and prevent regressions.

**Overall TDD Approach:**

For each step below, the workflow is:

1.  **Write Failing Test:** Add the test case described for the step using `pytest` conventions.
2.  **Run `pytest`:** Execute `pytest` in your terminal. Confirm the *new* test fails with an expected error (e.g., `AssertionError`, `404 Not Found`, `KeyError`) and that all *other* tests still pass.
3.  **Write Minimal Code:** Implement only the necessary application code (in routes, templates, services, etc.) to make the failing test pass.
4.  **Run `pytest`:** Execute `pytest` again. Confirm the new test now passes, and all previously passing tests *still* pass.
5.  **Refactor (Optional):** Improve the implementation code (e.g., clarity, efficiency) while ensuring all tests continue to pass by running `pytest` after refactoring.

---

**Refined TDD Plan with Explicit Steps:**

1.  **Feature: Add "Create Conversation" Link to List Page**
    *   **(Red)** Write Test: In `tests/test_api/test_list_conversations.py`, add a new test function `test_create_conversation_link_present`. Use `httpx` client (authenticated) to `GET /conversations`. Use `selectolax` to parse the response HTML. Assert that an element `a[href="/conversations/new"]` exists.
    *   **(Run)** Run `pytest`. Verify `test_create_conversation_link_present` fails (e.g., `AssertionError: Expected element 'a[href="/conversations/new"]' not found`) and other tests pass.
    *   **(Green)** Write Code: In `templates/conversations/list.html`, add the link: `<a href="{{ url_for('get_new_conversation_form') }}">Create New Conversation</a>`. (Ensure the route name `get_new_conversation_form` matches the one you'll define in the next step).
    *   **(Run)** Run `pytest`. Verify `test_create_conversation_link_present` and all other tests pass.
    *   **(Refactor)** Review the template change; refactoring is likely minimal here.

2.  **Feature: Create New Conversation Form Page (`GET /conversations/new`)**
    *   **(Red)** Write Test (Success Case): In `tests/test_api/test_conversation_routes.py` (or similar), add `test_get_new_conversation_form_success`. Use an authenticated `httpx` client to `GET /conversations/new`. Assert status code 200, `Content-Type: text/html`, and presence of `<form action="/conversations" method="post">` and inputs named `invitee_username` and `initial_message` in the HTML response.
    *   **(Run)** Run `pytest`. Verify `test_get_new_conversation_form_success` fails (likely 404).
    *   **(Green)** Write Code (Route): In `app/api/routes/conversations.py`, add a new route `@router.get("/conversations/new", response_class=HTMLResponse, name="get_new_conversation_form")`. Define the async function `get_new_conversation_form(request: Request, user: User = Depends(current_active_user))`. Initially, have it return a placeholder `TemplateResponse` for `conversations/new.html`.
    *   **(Run)** Run `pytest`. Test might now fail on content assertions.
    *   **(Green)** Write Code (Template): Create `templates/conversations/new.html`. Add the basic HTML structure and the required form (`<form action="{{ url_for('create_conversation') }}" method="post">`), including `<input type="text" name="invitee_username">` and `<textarea name="initial_message"></textarea>`, plus a submit button. Update the route function to render this template correctly. (Ensure route name `create_conversation` matches the POST route).
    *   **(Run)** Run `pytest`. Verify `test_get_new_conversation_form_success` passes.
    *   **(Red)** Write Test (Auth): Add `test_get_new_conversation_form_unauthenticated`. Use an *unauthenticated* `httpx` client to `GET /conversations/new`. Assert status code is 401 (or redirect status code if your auth handles it that way).
    *   **(Run)** Run `pytest`. Verify `test_get_new_conversation_form_unauthenticated` fails (likely gets 200 because auth isn't enforced yet).
    *   **(Green)** Write Code: Ensure `user: User = Depends(current_active_user)` is present in the `get_new_conversation_form` route signature.
    *   **(Run)** Run `pytest`. Verify `test_get_new_conversation_form_unauthenticated` and all other tests pass.
    *   **(Refactor)** Review route and template code for clarity.

3.  **Feature: Handle Form Submission (`POST /conversations`)**
    *   **(Red)** Write Test (Success Case): In `tests/test_api/test_create_conversation.py`, add/adapt `test_create_conversation_success_with_username`. Use an authenticated `httpx` client. Send a `POST` request to `/conversations` with `Content-Type: application/x-www-form-urlencoded` and data like `{"invitee_username": "existing_online_user", "initial_message": "Test message"}`. Assert status code 302/303, a valid `Location` header like `/conversations/some-slug`, and perform DB checks (Conversation created, creator 'joined', invitee 'invited', Message created). Setup requires creating the users (creator and invitee) in the DB beforehand, ensuring the invitee is online.
    *   **(Run)** Run `pytest`. Verify `test_create_conversation_success_with_username` fails (e.g., 422 if expecting JSON, or error in logic if trying to use username as ID).
    *   **(Green)** Write Code: Modify the `create_conversation` route signature in `app/api/routes/conversations.py` to accept form data: `invitee_username: str = Form(...)`, `initial_message: str = Form(...)`. Update the route logic:
        *   Use the `invitee_username` to query the database/service for the `invitee_user_id`. Handle `UserNotFound` or `UserOffline` errors appropriately (raising HTTPException 404 or 400).
        *   Call the underlying service method (`conv_service.create_new_conversation`) passing the resolved `invitee_user_id`.
        *   **(Change from API spec):** Instead of returning 201 JSON, return a `RedirectResponse(url=f"/conversations/{new_conversation.slug}", status_code=status.HTTP_303_SEE_OTHER)` on success.
    *   **(Run)** Run `pytest`. Verify `test_create_conversation_success_with_username` passes.
    *   **(Red->Green->Run Cycle for Failures):** Write tests for failure cases (`invalid_username`, `offline_user`, `missing_data`, `unauthenticated`) submitting *form data*. For each test: Write -> Run `pytest` (fail) -> Add code to handle the specific error in the route (e.g., check if user exists/is online, raise appropriate `HTTPException`) -> Run `pytest` (pass).
    *   **(Refactor)** Clean up the route logic.

4.  **Refactor: Decouple `POST /conversations` Logic**
    *   **(Refactor Step 1 - Define Handler):** Create `handle_create_conversation(invitee_username: str, initial_message: str, creator_user: User, conv_service: ConversationService) -> str:` (returning the slug) probably within `app/services/conversation_service.py` or a new `app/logic/conversation_processing.py`.
    *   **(Refactor Step 2 - Move Logic):** Cut the core logic (username lookup, service call) from the `create_conversation` route function and paste it into `handle_create_conversation`. Ensure the handler function raises the specific service exceptions (`UserNotFoundError`, `BusinessRuleError`, etc.) instead of `HTTPException`. It should return the `new_conversation.slug` on success.
    *   **(Refactor Step 3 - Update Route):** Modify the `create_conversation` route function in `conversations.py`:
        *   It should now call `handle_create_conversation`, passing the form data and dependencies (`user`, `conv_service`).
        *   Wrap the call in a `try...except` block to catch the specific service exceptions raised by the handler and translate them into appropriate `HTTPException`s (similar to the `handle_service_error` pattern).
        *   On successful return from the handler (getting the slug), create and return the `RedirectResponse`.
    *   **(Run)** Run `pytest`. **Crucially, all API tests written in Step 3 must still pass.** If any fail, debug the refactoring until they all pass again. This confirms the refactoring didn't change behavior.

5.  **Contract Test: Consumer (Frontend Simulation)**
    *   **(Write/Run Consumer Test):** Write the `test_consumer_conversation_form.py` pact test defining the `GET /conversations/new` and `POST /conversations` (with form data) interactions. Run the pact consumer test script. This generates `consumer-aimagain-api.json` in your pacts directory. *This step is outside the `pytest` flow.*

6.  **Contract Test: Provider (API Verification)**
    *   **(Setup Provider States):** Implement the necessary provider state setup functions in `tests/test_contract/conftest.py` (e.g., `_setup_user_authenticated`, `_setup_user_authenticated_and_target_online`).
    *   **(Red)** Write Test: Create `test_provider_conversation_api.py`. Add `test_provider_conversation_api_pact_verification`. Include the `pytest.mark.parametrize` setup to inject the `provider_server`. Inside the parametrization, specify the dependency override for the `handle_create_conversation` function (created in Step 4). Configure its mock return value for the "Submit Form (Success)" interaction to return a dummy slug (e.g., `"mock-slug"`).
    *   **(Run)** Run `pytest --provider-test` (or however you tag/run provider tests). Verify the new provider test fails (Pact verification error).
    *   **(Green)** Write Code: Ensure the provider state setup functions correctly prepare the DB state. Double-check that the `POST /conversations` route handler in `conversations.py` correctly translates the return value (the slug) from the (mocked) `handle_create_conversation` into a `RedirectResponse(status_code=303, url="/conversations/mock-slug")` which matches the expectation in the pact file.
    *   **(Run)** Run `pytest --provider-test` again. Verify the provider test now passes.
    *   **(Refactor)** Review provider state setup and mock configuration for clarity.

This detailed plan provides a clear TDD path for each feature, using `pytest` as the feedback loop to ensure correctness and prevent regressions at each stage.
