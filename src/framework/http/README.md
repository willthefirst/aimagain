# HTTP: cross-cutting plumbing

Cross-cutting HTTP plumbing — error translation, response shaping, form parsing, ASGI middleware. None of it knows what a domain entity is.

## Files

- `exceptions.py` — `APIException` base + `NotFoundError`, `ForbiddenError`, `BadRequestError`, `UnauthorizedError`, `InternalServerError`. Plus `handle_fastapi_users_error(...)` which translates fastapi-users exceptions (`UserAlreadyExists`, `InvalidPasswordException`) into the project's 4xx shape. Handlers raise; the decorator chain in `decorators.py` passes them through unchanged.
- `decorators.py` — `handle_route_errors`, the decorator the framework wraps every route in. Logs entry/exit, lets `APIException` subclasses bubble (they're `HTTPException` so FastAPI's default response builder shapes them), translates fastapi-users errors, converts anything else into a generic 500.
- `responses.py` — `APIResponse` helpers (`created_response`, `updated_response`, `refreshed_response`, `deleted_response`), `base_context(current_user)` (chrome scalars merged into every HTML render), `html_response(...)`.
- `forms.py` — `parse_form_to_payload(request)` (form → dict, lists for repeated keys), `validate_or_422(adapter, payload_dict)` (runs a Pydantic `TypeAdapter`, translates `ValidationError` into the project's 422 shape), and the convenience wrappers `parse_and_validate_form` / `parse_and_validate_json`.
- `form_rerender.py` — `form_rerender(request, template_name, context, field_errors=, form_banner=, values=)` re-renders a form template with `form_errors` / `form_values` / `form_banner` injected into the render context. Generic over the error *source* (Pydantic 422 → `mount_create`; fastapi-users 400 → `auth_pages.post_login`). The macro layer in `src/framework/templates/_shared/form_fields.html` reads `form_errors` / `form_values` when the template imports macros `with context`; `_shared/form_banner.html` reads `form_banner`. Pages opting in must (1) import macros `with context`, (2) drop `{{ form_banner() }}` at the top of the form, (3) set `hx-target="this" hx-swap="outerHTML"` on the `<form>`.
- `form_error_handler.py` — route decorator. Declarative version of "wrap the body in try/except → form_rerender". Takes `template=`, `prefill_fields=`, and a `handlers={ExceptionType: (e -> FormError)}` dict; on a matched exception it short-circuits to `form_rerender`, otherwise it re-raises so the outer `handle_route_errors` does its usual JSON-4xx translation. `require_htmx=True` (default) gates the rerender on the `HX-Request` header for routes that preserve a JSON contract for programmatic clients (e.g. `/auth/register`); `require_htmx=False` is for browser-only routes that have no parallel JSON endpoint (e.g. `/auth/login` — programmatic clients use `/auth/jwt/login`). Used by `register_request_handler` and `post_login`. Routes that bridge a non-exception failure (e.g. "the manager returned None") raise a module-private sentinel exception and register a handler for it, keeping the rerender path declarative.
- `middleware.py` — `StripEmptyQueryParamsMiddleware` (drops `?x=` empty pairs from form submissions so "filter not selected" behaves like "filter omitted").

## Tests

`test_responses.py`, `test_middleware.py`. The decorator + exception behavior is exercised through route tests under `src/domain/routes/`.
