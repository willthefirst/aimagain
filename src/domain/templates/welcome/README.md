# Welcome wizard templates

Templates for the `/welcome/*` bespoke router (`src/domain/routes/welcome.py`).

## Layout

`_layout.html` extends `base.html` and provides the wizard page chrome:
- Optional step header (via `step_info` context variable, e.g. `"Step 1 of 1"`)
- `{% block wizard_content %}{% endblock %}` for each step's body

Each step template extends `_layout.html` and fills `wizard_content`.

## Steps

| File | URL | Description |
|---|---|---|
| `verify.html` | `GET /welcome/verify` | License-verification form (Step 1 of 1 for all flows) |
| `first_opening.html` | `GET /welcome/first-opening` | First opening form (Step 2 of 2 for `have_openings` flow) |
| `done.html` | `GET /welcome/done` | Terminal "You're on the board" page (`have_openings` flow) |
| `be_findable.html` | `GET /welcome/be-findable` | Specialties + modality form (Step 2 of 2 for `refer_now` flow) |
| `coming_soon.html` | `GET /welcome/coming-soon` | Placeholder while T7 steps ship |
| `refer.html` | `GET /welcome/refer/{opening_id}` | Send-referral form for a specific clinician opening |

`refer.html` receives `opening_detail` (an `OpeningDetail` ORM row), `clinician`
(the linked `Clinician`, or `None`), and `refer_url` (the POST action URL for
the form). The form submits `target_opening_id` (hidden) and `clinical_context`
(textarea) to `POST /welcome/refer/{opening_id}`.

## Steps (downstream)

T7 adds `start_network.html`, `minimal_profile.html`. Each follows the same
pattern: extend `_layout.html`, fill `wizard_content`, form via `form_with_errors`
macro.

## Styling note

Deliberately minimal — no custom CSS, no chip components, no color tokens.
A basecoat.ui migration will style wizard pages after the epic is complete.
