# Rendering: Jinja + form glue

Jinja templating engine + form-rendering glue + per-viewer response projections. Generic; the per-entity HTML lives in [`../../domain/templates/`](../../domain/templates/).

## Files

- `templating.py` — Jinja `Environment` setup with `FileSystemLoader("src/domain/templates")`, the controlled-vocabulary tuples from `../../domain/models/enums.py` exposed as Jinja globals, and `register_choice_labels(...)` populating the choice-tuple → label-dict registry that `field_spec(...)` consumes. The `templates` `Jinja2Templates` instance + `get_template_context()` helper are the public interface.
- `form_fields.py` — `HtmlPattern` / `HtmlTextarea` (Pydantic annotation markers — the former carries HTML pattern/maxlength hints, the latter swaps `<input type=text>` for `<textarea>`) and `field_spec(schema_cls, name)` (introspects a Pydantic schema's `FieldInfo` and returns a normalized dict the `field_for` Jinja macro dispatches on). Lets templates derive their `<input>` attributes from the same Pydantic field that validates the request.
- `projections.py` — `project_view(obj, *, public_fields, actor, private_fields=(), private_field_predicate=None)` builds a dict of `public_fields` from `obj` and conditionally appends `private_fields` when the predicate is true. Defense-in-depth alongside template `{% if %}` guards: omitting keys at projection time means a forgotten template guard can't re-leak.

## Schema-driven form rendering

`field_for(schema, name, label, current=None, required=None)` (in `domain/templates/_shared/form_fields.html`) calls the `field_spec` Jinja global at render time to derive the form's HTML attributes from the schema. The schema's `Literal[*TUPLE]` becomes a `<select>`; an `Annotated[T, HtmlPattern(...)]` becomes `pattern` / `maxlength` on the `<input>`; an `Annotated[T, HtmlTextarea()]` becomes a `<textarea>`. Adding a value to a controlled-vocabulary tuple flows automatically to every form using these macros — no per-template edits.

## Tests

`test_templating.py`, `test_form_fields.py`, `test_projections.py` — each covering its module.
