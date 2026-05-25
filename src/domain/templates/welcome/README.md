# Welcome wizard templates

Templates for the `/welcome/*` bespoke router (`src/domain/routes/welcome.py`).

## Layout

`_layout.html` extends `base.html` and provides the wizard page chrome:
- Optional step header (via `step_info` context variable, e.g. `"Step 1 of 1"`)
- `{% block wizard_content %}{% endblock %}` for each step's body

Each step template extends `_layout.html` and fills `wizard_content`.

## Steps (this ticket)

| File | URL | Description |
|---|---|---|
| `verify.html` | `GET /welcome/verify` | License-verification form |
| `coming_soon.html` | `GET /welcome/coming-soon` | Placeholder while downstream steps ship |

## Steps (downstream)

T4/T5/T6/T7 add `first_opening.html`, `done.html`, `be_findable.html`,
`refer.html`, `start_network.html`, `minimal_profile.html`. Each follows the
same pattern: extend `_layout.html`, fill `wizard_content`, form via
`form_with_errors` macro.

## Styling note

Deliberately minimal — no custom CSS, no chip components, no color tokens.
A basecoat.ui migration will style wizard pages after the epic is complete.
