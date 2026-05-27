"""Domain-side Jinja globals.

The framework's templating env (`src/framework/rendering/templating.py`)
deliberately knows no entity-specific values. This module is where every
domain enum, per-kind create schema, and view helper is wired into the
env via `register_template_globals(...)` and `register_choice_labels(...)`.

Import-time side effects: the registration calls run when this module
loads, so callers ensure the trigger fires before any template renders.
Two trigger points cover the real load paths:

* `src/main.py` imports this module at app boot.
* `src/domain/__init__.py` re-imports it so any `from src.domain.X import Y`
  in a test or script populates the env before a render reaches for a
  global.
"""

from src.domain.logic.clinicians.view import clinician_card_view
from src.domain.logic.posts.schema import (
    ClinicianOpeningCreate,
    ProgramIntakeCreate,
    ReferralCreate,
)
from src.domain.logic.posts.view import (
    insurance_posture_for_post,
    post_card_view,
    post_feed_headline,
    post_row_summary,
    referral_headline,
)
from src.domain.models import enums
from src.framework.rendering.form_fields import register_choice_labels
from src.framework.rendering.templating import register_template_globals

# Expose the controlled-vocabulary tuples (and matching display-label
# dicts) from `src/domain/models/enums.py` as Jinja globals so per-kind
# form templates iterate over the same values that the schema's
# `Literal[*TUPLE]`s and the DB CHECK constraints render from. Adding a
# value to a tuple in `enums.py` then shows up everywhere — schema,
# DB, and form dropdown — without per-template edits. The label dicts
# are looked up in the form-render macro
# (`src/framework/templates/_shared/form_fields.html`); the
# `test_labels_cover_their_tuples` guardrail asserts every value in a
# tuple has a label.
register_template_globals(
    US_STATES=enums.US_STATES,
    LOCATION_AVAILABILITY_OPTIONS=enums.LOCATION_AVAILABILITY_OPTIONS,
    LOCATION_AVAILABILITY_LABELS=enums.LOCATION_AVAILABILITY_LABELS,
    CLIENT_AGE_GROUPS=enums.CLIENT_AGE_GROUPS,
    CLIENT_AGE_GROUP_LABELS=enums.CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUP_LABELS_SINGULAR=enums.CLIENT_AGE_GROUP_LABELS_SINGULAR,
    LANGUAGES=enums.LANGUAGES,
    LANGUAGE_LABELS=enums.LANGUAGE_LABELS,
    NETWORK_PREFERENCES=enums.NETWORK_PREFERENCES,
    NETWORK_PREFERENCE_LABELS=enums.NETWORK_PREFERENCE_LABELS,
    INSURANCE_CARRIERS=enums.INSURANCE_CARRIERS,
    INSURANCE_CARRIER_LABELS=enums.INSURANCE_CARRIER_LABELS,
    DESIRED_TIME_SLOTS=enums.DESIRED_TIME_SLOTS,
    DESIRED_TIME_SLOT_LABELS=enums.DESIRED_TIME_SLOT_LABELS,
    DESIRED_TIME_DAYS=enums.DESIRED_TIME_DAYS,
    DESIRED_TIME_DAY_LABELS=enums.DESIRED_TIME_DAY_LABELS,
    DESIRED_TIME_DAY_SHORT_LABELS=enums.DESIRED_TIME_DAY_SHORT_LABELS,
    DESIRED_TIME_PARTS=enums.DESIRED_TIME_PARTS,
    DESIRED_TIME_PART_LABELS=enums.DESIRED_TIME_PART_LABELS,
    REFERRAL_SERVICES=enums.REFERRAL_SERVICES,
    REFERRAL_SERVICE_LABELS=enums.REFERRAL_SERVICE_LABELS,
    TREATMENT_SETTINGS=enums.TREATMENT_SETTINGS,
    TREATMENT_SETTINGS_LABELS=enums.TREATMENT_SETTINGS_LABELS,
    GENDERS=enums.GENDERS,
    GENDER_LABELS=enums.GENDER_LABELS,
    # Lucide icon names per enum value — consumed by the listing-row
    # macro in `src/domain/templates/posts/_item.html`. Renaming a label
    # leaves these untouched; adding/renaming an *enum value* must touch
    # the icons dict too (`test_icons_cover_their_tuples` guard fires
    # otherwise).
    CLIENT_AGE_GROUP_ICONS=enums.CLIENT_AGE_GROUP_ICONS,
    REFERRAL_SERVICE_ICONS=enums.REFERRAL_SERVICE_ICONS,
    TREATMENT_SETTINGS_ICONS=enums.TREATMENT_SETTINGS_ICONS,
    INSURANCE_POSTURES=enums.INSURANCE_POSTURES,
    INSURANCE_POSTURE_LABELS=enums.INSURANCE_POSTURE_LABELS,
    INSURANCE_POSTURE_ICONS=enums.INSURANCE_POSTURE_ICONS,
    # `LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES` and
    # their `_LABELS` are clinician-only — they flow into the context
    # via `CLINICIAN_ENTITY.static_context` (merged by `handle_detail` /
    # `handle_list` / `handle_get_edit_form`) so the spec is the single
    # binding site. `register_choice_labels(...)` for those tuples
    # stays below (the form-rendering macro looks up labels by tuple
    # identity, not by Jinja global).
    #
    # Polymorphic posts have no single create-schema (the top-level
    # adapter is a discriminated union); the per-kind route handler
    # can't inject a `schema` context var without per-kind plumbing in
    # `PostKindSpec`, which would close an import cycle (post_kinds →
    # schema → models → post_kinds). Exposing the kind-specific
    # `*Create` schemas as Jinja globals lets the kind's form templates
    # pass the right schema to `field_for` without context-routing
    # changes. Per-kind form templates pick which to pass.
    opening_create_schema=ClinicianOpeningCreate,
    intake_create_schema=ProgramIntakeCreate,
    referral_create_schema=ReferralCreate,
    # Post-specific view helpers.
    insurance_posture=insurance_posture_for_post,
    referral_headline=referral_headline,
    # `post_card_view(post)` is the unified view-model both the listing
    # card (`posts/_item.html`) and the detail page (`posts/detail.html`)
    # read from — see its docstring in `src.domain.logic.posts.view`.
    post_card_view=post_card_view,
    # `post_row_summary(post)` — compact mid-dot summary line for the row
    # layout used by the home-page widget and list-page compact view.
    post_row_summary=post_row_summary,
    # `post_feed_headline(post)` — two-part "<identity> — <focus>" headline
    # for the feed-row component in home and browse list views.
    post_feed_headline=post_feed_headline,
    # `clinician_card_view(clinician)` is the unified view-model
    # `clinicians/detail.html` reads from — see its docstring in
    # `src.domain.logic.clinicians.view`.
    clinician_card_view=clinician_card_view,
)

# Register the choice-tuple → labels-dict mapping that `field_spec` uses
# to resolve labels for `Literal[*TUPLE]` fields. Lookup is by tuple
# identity, so the mapping needs to be populated before any template
# render. Tuples without a labels dict (USPS state codes are
# self-describing) register `None` so misses are explicit.
register_choice_labels(enums.US_STATES, None)
register_choice_labels(
    enums.LOCATION_AVAILABILITY_OPTIONS, enums.LOCATION_AVAILABILITY_LABELS
)
register_choice_labels(enums.CLIENT_AGE_GROUPS, enums.CLIENT_AGE_GROUP_LABELS)
register_choice_labels(enums.LANGUAGES, enums.LANGUAGE_LABELS)
register_choice_labels(enums.NETWORK_PREFERENCES, enums.NETWORK_PREFERENCE_LABELS)
register_choice_labels(enums.INSURANCE_CARRIERS, enums.INSURANCE_CARRIER_LABELS)
register_choice_labels(enums.REFERRAL_SERVICES, enums.REFERRAL_SERVICE_LABELS)
register_choice_labels(enums.TREATMENT_SETTINGS, enums.TREATMENT_SETTINGS_LABELS)
register_choice_labels(enums.GENDERS, enums.GENDER_LABELS)
register_choice_labels(enums.LICENSE_TYPES, enums.LICENSE_TYPES_LABELS)
register_choice_labels(enums.EDUCATION_TYPES, enums.EDUCATION_TYPES_LABELS)
register_choice_labels(enums.CERTIFICATION_TYPES, enums.CERTIFICATION_TYPES_LABELS)
