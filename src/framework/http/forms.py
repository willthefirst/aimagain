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
    """
    form_data = await request.form()
    payload: dict = {}
    for key in form_data:
        values = form_data.getlist(key)
        payload[key] = values if len(values) > 1 else values[0] if values else None
    return payload


def validate_or_422(adapter: TypeAdapter, payload_dict: dict):
    """Run a payload dict through a `TypeAdapter`; translate Pydantic
    `ValidationError` to HTTP 422 with a JSON-serializable error list.

    The error shape — `[{"loc", "msg", "type"}, ...]` — matches what the
    posts and provider routes have been emitting since their
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
