"""HTTP-adapter primitives for form-encoded route bodies.

These helpers are the cross-cutting glue between FastAPI's request object
and the Pydantic schemas used by the logic layer. Per
`src/framework/README.md`, this module is the home for any HTTP-adapter
primitive that two or more route modules would otherwise import from each
other (the same smell #157 catches one layer over).
"""

from fastapi import HTTPException, Request
from pydantic import TypeAdapter, ValidationError


async def parse_form_to_payload(request: Request) -> dict:
    """Parse a form-encoded request body into a payload dict.

    For form-encoded requests with multiple values for the same key
    (e.g. checkboxes that submit the same name several times), the values
    are returned as a list. A single value is returned as a scalar so
    schemas typed as `str | None` keep working.

    **Checkbox-with-hidden Rails pattern:** the `checkbox_field` macro
    emits a `<input type="hidden" name="x" value="false">` immediately
    before the `<input type="checkbox" name="x" value="true">` so that
    default-true booleans round-trip when the user unchecks the box
    (the hidden value carries the negative; the checkbox overrides
    when checked). That produces a list of bool strings on the wire —
    `["false"]` when unchecked, `["false", "true"]` when checked. When
    every value in a repeated-key list is exactly `"true"` or
    `"false"`, last-wins applies and the payload entry becomes the
    final value as a scalar string — Pydantic's `bool` validator then
    accepts it like any single-value checkbox post.

    Multi-select fields are unaffected: their controlled-vocabulary
    options (`"in_person"`, `"morning"`, `"monday_am"`, etc.) never
    consist solely of `"true"`/`"false"` tokens, so the heuristic
    doesn't fire on them.
    """
    form_data = await request.form()
    payload: dict = {}
    for key in form_data:
        values = form_data.getlist(key)
        if len(values) > 1 and all(v in ("true", "false") for v in values):
            # Rails checkbox+hidden pattern → last wins as a scalar.
            payload[key] = values[-1]
        else:
            payload[key] = values if len(values) > 1 else values[0] if values else None
    return payload


def validate_or_422(adapter: TypeAdapter, payload_dict: dict):
    """Run a payload dict through a `TypeAdapter`; translate Pydantic
    `ValidationError` to HTTP 422 with a JSON-serializable error list.

    The error shape — `[{"loc", "msg", "type"}, ...]` — matches what the
    posts and clinician routes have been emitting since their
    respective issues landed. HTMX form clients depend on the `loc`/`msg`
    pair to attach inline error text to the offending field.
    """
    try:
        return adapter.validate_python(payload_dict)
    except ValidationError as e:
        errors = [
            {"loc": err["loc"], "msg": err["msg"], "type": err["type"]}
            for err in e.errors()
        ]
        raise HTTPException(status_code=422, detail=errors)


async def parse_and_validate_form(request: Request, adapter: TypeAdapter):
    """Parse a form-encoded request and validate it through `adapter`.

    Combines the `parse_form_to_payload` and `validate_or_422` pair that
    every form-encoded mutating route runs back-to-back. The underlying
    primitives stay public for routes that need to inspect or transform
    the parsed dict between the two steps.
    """
    payload_dict = await parse_form_to_payload(request)
    return validate_or_422(adapter, payload_dict)


async def parse_and_validate_json(request: Request, adapter: TypeAdapter):
    """Parse a JSON request body and validate it through `adapter`.

    Mirrors `parse_and_validate_form` for state-axis subresources whose
    PUT bodies arrive as JSON (e.g. `PUT /users/{id}/activation`). Form
    encoding is the standard for HTML forms; state-axis flips are
    typically issued by HTMX with a JSON body since there's no form to
    submit (just a button).
    """
    try:
        payload_dict = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    return validate_or_422(adapter, payload_dict)
