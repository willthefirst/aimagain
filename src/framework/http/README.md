# HTTP: cross-cutting plumbing

Cross-cutting HTTP plumbing — error translation, response shaping, form parsing, ASGI middleware. None of it knows what a domain entity is.

## Files

- `exceptions.py` — `APIException` base + `NotFoundError`, `ForbiddenError`, `BadRequestError`, `UnauthorizedError`, `InternalServerError`. Plus `handle_fastapi_users_error(...)` which translates fastapi-users exceptions (`UserAlreadyExists`, `InvalidPasswordException`) into the project's 4xx shape. Handlers raise; the decorator chain in `decorators.py` passes them through unchanged.
- `decorators.py` — `handle_route_errors`, the decorator the framework wraps every route in. Logs entry/exit, lets `APIException` subclasses bubble (they're `HTTPException` so FastAPI's default response builder shapes them), translates fastapi-users errors, converts anything else into a generic 500.
- `responses.py` — `APIResponse` helpers (`created_response`, `updated_response`, `refreshed_response`, `deleted_response`), `base_context(current_user)` (chrome scalars merged into every HTML render), `html_response(...)`.
- `forms.py` — `parse_form_to_payload(request)` (form → dict, lists for repeated keys), `validate_or_422(adapter, payload_dict)` (runs a Pydantic `TypeAdapter`, translates `ValidationError` into the project's 422 shape), and the convenience wrappers `parse_and_validate_form` / `parse_and_validate_json`.
- `middleware.py` — `StripEmptyQueryParamsMiddleware` (drops `?x=` empty pairs from form submissions so "filter not selected" behaves like "filter omitted").

## Tests

`test_responses.py`, `test_middleware.py`. The decorator + exception behavior is exercised through route tests under `src/domain/routes/`.
