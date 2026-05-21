# Domain templates

Per-entity Jinja templates. One cluster directory per resource (`providers/`, `users/`, `posts/`, `favorites/`, `auth/`); cluster-local partials are prefixed `_`.

Chrome, shared macros, and the generic view-type templates live in [`../../framework/templates/`](../../framework/templates/) — see its README for the full contract, including the page-chrome strips, the layering rule, and the four view-type templates (`views/list.html`, `views/detail.html`, `views/form_new.html`, `views/form_edit.html`) that this directory's pages extend.

## Per-cluster grammar

A resource cluster `<entity>/` typically contains:

- `list.html` — extends `views/list.html`. Declares `resource_label`, an optional `actions` block (right-aligned toolbar items, each an `<li>` inside `<menu class="toolbar-right">`), and a `content` block: a `<section id="<collection>-list">` of cards rendered through `_shared/_card.html` (or a resource-specific card macro like `_shared/_clinician_card.html`). The toolbar's filter link is rendered automatically by `views/list.html` from spec-driven context (`active_filters`, `search_url`) that `handle_list` injects — no per-template wiring needed.
- `search.html` — extends `views/search.html`. One-line stub setting the `resource_label` breadcrumb for entities that opt into `routes.search=True`. Renders one form control per declared secondary `Filter` on the spec.
- `detail.html` — extends `views/detail.html`. Declares `resource_label`, `current_label`, `resource_url`, optional `actions`, and `content`.
- `form_new.html` — extends `views/form_new.html`. Declares `resource_label`, `resource_url`, and the form body in `content`.
- `form_edit.html` — extends `views/form_edit.html`. Declares `resource_label`, `current_label`, `resource_url`, `resource_detail_url`, and the form body in `content`.
- `_<role>_actions.html` (cluster-local partial) — owner/admin action button clusters for the entity, `{% include %}`d from the detail page's `actions` block or the card footer on the list page.

Subresource lists (e.g. `/users/{id}/clinicians`) override `{% block breadcrumb %}` to land a multi-segment chain (`Users › <username> › Clinicians`) while still inheriting the list view's toolbar + content shape from `views/list.html`. See `users/providers_list.html` (file name retained — the directory cluster is still `providers/` because the model class is `Provider`; only the user-facing surface flipped in #642 PR 4).

Pages that don't fit the resource grammar — the `/auth/*` flow's centered single-card layout — extend `base.html` directly and compose the `_shared/` macros by hand.

Post templates nest under a `posts/` cluster (sibling sub-clusters per URL family, plus a `_shared/` for cross-face partials):

```
posts/
├── _shared/              ← cross-face partials (_item, _facts_block, _owner_actions, …)
├── referrals/            ← /referrals face (kind-locked leaf, kind='referral')
│   ├── list.html, detail.html, search.html, form_new.html, form_edit.html
│   └── _form.html (create/edit form-body macro)
└── openings/             ← /openings face (subset-supertype over clinician_opening + program_intake)
    ├── list.html, detail.html, search.html
    ├── form_new.html (picker), form_edit.html (kind-dispatch fallback)
    ├── new_clinician_opening.html, edit_clinician_opening.html, _form_clinician_opening.html
    └── new_program_intake.html, edit_program_intake.html, _form_program_intake.html
```

The handler sets `template_name = POST_KINDS[kind].create_template` (or `edit_template`) to pick the right per-subkind form by the `?kind=` URL param or the row's stored kind. The `_post_face` builder in [`../specs/posts/_base.py`](../specs/posts/_base.py) sets `templates=Templates(list="posts/<face>/list.html", …)` for each face's primary verbs.

The cross-resource import lint ([`scripts/dev/template_imports_check.py`](../../../scripts/dev/template_imports_check.py)) permits a sub-cluster (`posts/<face>/`) to import from its parent cluster's `_shared/` (`posts/_shared/`) — that's how the per-face templates pull in shared post-card partials without crossing a boundary. Sibling sub-clusters (`posts/openings/` ↔ `posts/referrals/`) still can't import from each other.

The services list is the first row of `_facts_block`'s `<dl>` rather than its own partial (see #628).

The auth-flow pages (`auth/login.html`, `auth/register.html`, `auth/forgot_password.html`, `auth/reset_password.html`) each render a single `<article class="auth-page">` card. The `.auth-page` rule in [`../../framework/templates/base.html`](../../framework/templates/base.html) caps the card at 28rem and centers it horizontally — without the class the card stretches to the full `<main class="container">` width on tablet/desktop.

## Copy style guide

Every label, legend, help string, button, and intro paragraph in `src/domain/templates/` follows the rules below. The audience is mental-health clinicians — copy reads as concise plain English, not clinical jargon. Pinned by [`test_copy_conventions.py`](test_copy_conventions.py); a violation surfaces as a test failure, not a code review note.

### Labels and legends

- **Sentence case.** `First name`, `In-network carriers`, `Treatment settings` — not `First Name` or `Treatment Settings`. Acronyms keep their canonical case (`NPI`, `ZIP`, `DBT`).
- **No trailing punctuation** unless the label is genuinely a question. `Sliding scale?` yes; `Last name.` no.
- **No app-internal abbreviations.** `Organization`, never `Org`. Domain acronyms every clinician already says aloud (`NPI`, `ZIP`) stay.

### Help text (`help=`)

- **Full sentence, period at the end.** `10-digit National Provider Identifier.` not `10-digit National Provider Identifier`.
- **Specific.** Explain *what the value is for*, not that the field exists. `For example: DBT, EMDR, IFS.` beats `Free text.`.
- **Never write `help="Optional."`.** The `(optional)` indicator on the label is the single canonical signal — see below.
- If the same help string appears in two or more forms, move it to [`../../framework/templates/_shared/form_copy.html`](../../framework/templates/_shared/form_copy.html) and import it.

### Optional fields

Pass `required=False` to any form-field macro. The macro renders a muted `(optional)` after the label automatically (see `_field_label` in [`../../framework/templates/_shared/form_fields.html`](../../framework/templates/_shared/form_fields.html)).

```jinja
{# OK — `(optional)` is rendered automatically #}
{{ text_field("npi", "NPI", required=False, help="10-digit National Provider Identifier.") }}

{# Bad — duplicates the (optional) indicator with prose #}
{{ text_field("npi", "NPI", required=False, help="Optional. 10-digit NPI.") }}
```

Fieldset-level "everything below is optional" lines (the previous `<small>Both lists optional.</small>` pattern) are gone — every field carries its own indicator now.

### Buttons

- **Verb-noun, sentence case.** `Create program`, `Post referral`, `Save changes`, `Send reset link`.
- **Create / edit submit pattern.** Create forms use `entity_create_label(spec.name, kind=...)` so the submit button text matches the H1 (`Create clinician opening` everywhere). Edit forms use `Save changes` — every edit form, no exceptions. The structural pin lives in `entity_create_label` (see [`../../framework/templates/README.md` § "Create / filter labels"](../../framework/templates/README.md)).

### Vocabulary

One word per concept, no synonyms. Replace any of the variants below in any new copy:

| Concept                    | Word                | Don't use                                |
| -------------------------- | ------------------- | ---------------------------------------- |
| Person who treats          | clinician           | provider, practitioner, therapist        |
| Person treated             | client              | patient                                  |
| Practice / employer entity | organization        | practice, clinic, group, agency          |
| Delivery format            | in-person / virtual | telehealth, remote, online               |
| The post type announcing availability for individual clinicians | opening | listing, slot, position |
| The post type announcing program-level intake | intake | enrollment, admission window |
| The post type seeking placement for a client | referral | seeker post, lead |

The model class `Provider` and the audit string `provider` are historical and kept on the Python side; user-facing copy says `clinician`. See `src/domain/specs/provider.py` for the rename rationale.

### Shared microcopy

Strings repeated across forms live in [`../../framework/templates/_shared/form_copy.html`](../../framework/templates/_shared/form_copy.html). Today:

- `org_picker_help()` — the "Can't find your organization?" hint for every Org-FK picker.
- `modality_help()` — the `e.g. DBT, EMDR, IFS` example for the treatment-modality free-text field.
- `select_all_help()` — the `Select all that apply.` hint for multi-choice demographics.

If a new string would otherwise live in two forms, add it here.

## Tests

Exercised indirectly via route tests under [`../routes/`](../routes/), plus [`test_copy_conventions.py`](test_copy_conventions.py) (this directory) which scans every template for forbidden patterns (literal `Optional.` help strings, `Org` abbreviation, etc.). Selector and fixture conventions live in [`../../../tests/README.md`](../../../tests/README.md).
