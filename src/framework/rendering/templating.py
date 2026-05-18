from datetime import date, datetime

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.domain.logic.posts.schema import (
    ClientReferralCreate,
    ProgramAvailabilityCreate,
    ProviderAvailabilityCreate,
)
from src.domain.models import enums
from src.framework.config import settings
from src.framework.rendering.form_fields import field_spec, register_choice_labels

auto_reload = settings.ENVIRONMENT == "development"


def format_post_date(value: datetime | date | None) -> str:
    """Craigslist-style short date — `May 15` for current-year posts,
    `May 15, 2025` for older. Used by the posts list/detail templates so
    the same timestamp reads the same way in both places.

    `%-d` strips a leading zero from the day (`May 5`, not `May 05`).
    Linux/macOS only; this app runs on neither Windows nor any platform
    that needs `%#d`. If that changes, swap to `strftime('%b %d').lstrip('0')`.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        return ""
    today = date.today()
    if d.year == today.year:
        return d.strftime("%b %-d")
    return d.strftime("%b %-d, %Y")


_env = Environment(
    # Two search roots: framework owns `base.html`, `_shared/` macros, and
    # the generic `views/` chrome; domain owns per-entity templates. The
    # FileSystemLoader resolves names by walking the list, so domain
    # templates can `{% extends "views/list.html" %}` (resolved from
    # framework) and reference `{% from "_shared/..." %}` the same way.
    loader=FileSystemLoader(["src/framework/templates", "src/domain/templates"]),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

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
_env.globals.update(
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
    CLIENT_REFERRAL_SERVICES=enums.CLIENT_REFERRAL_SERVICES,
    CLIENT_REFERRAL_SERVICE_LABELS=enums.CLIENT_REFERRAL_SERVICE_LABELS,
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
    CLIENT_REFERRAL_SERVICE_ICONS=enums.CLIENT_REFERRAL_SERVICE_ICONS,
    TREATMENT_SETTINGS_ICONS=enums.TREATMENT_SETTINGS_ICONS,
    INSURANCE_POSTURES=enums.INSURANCE_POSTURES,
    INSURANCE_POSTURE_LABELS=enums.INSURANCE_POSTURE_LABELS,
    INSURANCE_POSTURE_ICONS=enums.INSURANCE_POSTURE_ICONS,
    # `LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES` and
    # their `_LABELS` are provider-only — they flow into the context
    # via `PROVIDER_ENTITY.static_context` (merged by `handle_detail` /
    # `handle_list` / `handle_get_edit_form`) so the spec is the single
    # binding site. `register_choice_labels(...)` for those tuples
    # stays below (the form-rendering macro looks up labels by tuple
    # identity, not by Jinja global).
    # Pydantic-driven field rendering: `field_for(schema, name, label)`
    # in `_shared/form_fields.html` calls `field_spec(schema, name)` to
    # derive the form's HTML attributes (required, choices, pattern,
    # maxlength) from the schema. The schema class itself is passed
    # into the template context by the route handler — keeps the
    # core → schemas import direction clean (see layer matrix in
    # `src/README.md`).
    field_spec=field_spec,
    # Polymorphic posts have no single create-schema (the top-level
    # adapter is a discriminated union); the per-kind route handler
    # can't inject a `schema` context var without per-kind plumbing in
    # `PostKindSpec`, which would close an import cycle (post_kinds →
    # schema → models → post_kinds). Exposing the kind-specific
    # `*Create` schemas as Jinja globals lets the kind's form templates
    # pass the right schema to `field_for` without context-routing
    # changes. Per-kind form templates pick which to pass.
    provider_availability_create_schema=ProviderAvailabilityCreate,
    program_availability_create_schema=ProgramAvailabilityCreate,
    client_referral_create_schema=ClientReferralCreate,
)

# Register the choice-tuple → labels-dict mapping that `field_spec`
# uses to resolve labels for `Literal[*TUPLE]` fields. Lookup is by
# tuple value, so the mapping needs to be populated before any
# template render. Tuples without a labels dict (USPS state codes are
# self-describing) register `None` so misses are explicit.
register_choice_labels(enums.US_STATES, None)
register_choice_labels(
    enums.LOCATION_AVAILABILITY_OPTIONS, enums.LOCATION_AVAILABILITY_LABELS
)
register_choice_labels(enums.CLIENT_AGE_GROUPS, enums.CLIENT_AGE_GROUP_LABELS)
register_choice_labels(enums.LANGUAGES, enums.LANGUAGE_LABELS)
register_choice_labels(enums.NETWORK_PREFERENCES, enums.NETWORK_PREFERENCE_LABELS)
register_choice_labels(enums.INSURANCE_CARRIERS, enums.INSURANCE_CARRIER_LABELS)
register_choice_labels(
    enums.CLIENT_REFERRAL_SERVICES, enums.CLIENT_REFERRAL_SERVICE_LABELS
)
register_choice_labels(enums.TREATMENT_SETTINGS, enums.TREATMENT_SETTINGS_LABELS)
register_choice_labels(enums.GENDERS, enums.GENDER_LABELS)
register_choice_labels(enums.LICENSE_TYPES, enums.LICENSE_TYPES_LABELS)
register_choice_labels(enums.EDUCATION_TYPES, enums.EDUCATION_TYPES_LABELS)
register_choice_labels(enums.CERTIFICATION_TYPES, enums.CERTIFICATION_TYPES_LABELS)

_env.filters["format_post_date"] = format_post_date

# Post-specific view helper. Lives in `domain/logic/posts/view.py`; the
# import goes through `domain.logic` (the framework would normally not
# import domain, but this template-context binding is the same site
# that already exposes domain enums + per-kind create schemas above).
from src.domain.logic.posts.view import (  # noqa: E402
    client_referral_headline,
    insurance_posture_for_post,
)

_env.globals["insurance_posture"] = insurance_posture_for_post
_env.globals["client_referral_headline"] = client_referral_headline

templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": "35729",
    }
