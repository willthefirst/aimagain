# Rendering: Jinja + form glue

Jinja templating engine + form-rendering glue + per-viewer response projections. Generic; the chrome and view-type templates live in [`../templates/`](../templates/) and per-entity pages in [`../../domain/templates/`](../../domain/templates/).

## Files

- `templating.py` — Jinja `Environment` setup with `FileSystemLoader(["src/framework/templates", "src/domain/templates"])` (two roots: framework owns the chrome + view-type templates, domain owns per-entity pages). Framework-owned globals are only `field_spec` (schema-driven form rendering) and the `format_post_date` filter. Domain enums, per-kind create schemas, and view helpers are registered from [`../../domain/template_globals.py`](../../domain/template_globals.py) via `register_template_globals(...)` and the existing `register_choice_labels(...)` API in `form_fields.py`. The `templates` `Jinja2Templates` instance + `get_template_context()` helper are the public interface.
- `form_fields.py` — `HtmlPattern` / `HtmlTextarea` (Pydantic annotation markers — the former carries HTML pattern/maxlength hints, the latter swaps `<input type=text>` for `<textarea>`) and `field_spec(schema_cls, name)` (introspects a Pydantic schema's `FieldInfo` and returns a normalized dict the `field_for` Jinja macro dispatches on). Lets templates derive their `<input>` attributes from the same Pydantic field that validates the request.
- `projections.py` — `project_view(obj, *, public_fields, actor, private_fields=(), private_field_predicate=None)` builds a dict of `public_fields` from `obj` and conditionally appends `private_fields` when the predicate is true. Defense-in-depth alongside template `{% if %}` guards: omitting keys at projection time means a forgotten template guard can't re-leak.

The schema-driven form-rendering contract (which annotation maps to which control) lives next to the macro that consumes `field_spec` — see [`../templates/README.md`](../templates/README.md#schema-driven-field_for).

## Tests

`test_templating.py`, `test_form_fields.py`, `test_projections.py` — each covering its module.
