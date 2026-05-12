from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.framework.config import settings
from src.framework.form_fields import field_spec, register_choice_labels
from src.models import enums

auto_reload = settings.ENVIRONMENT == "development"

_env = Environment(
    loader=FileSystemLoader("src/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

# Expose the controlled-vocabulary tuples (and matching display-label
# dicts) from `src/models/enums.py` as Jinja globals so per-kind
# form templates iterate over the same values that the schema's
# `Literal[*TUPLE]`s and the DB CHECK constraints render from. Adding a
# value to a tuple in `enums.py` then shows up everywhere — schema,
# DB, and form dropdown — without per-template edits. The label dicts
# are looked up in the form-render macro
# (`src/templates/_shared/form_fields.html`); the
# `test_labels_cover_their_tuples` guardrail asserts every value in a
# tuple has a label.
_env.globals.update(
    US_STATES=enums.US_STATES,
    LOCATION_AVAILABILITY_OPTIONS=enums.LOCATION_AVAILABILITY_OPTIONS,
    LOCATION_AVAILABILITY_LABELS=enums.LOCATION_AVAILABILITY_LABELS,
    CLIENT_AGE_GROUPS=enums.CLIENT_AGE_GROUPS,
    CLIENT_AGE_GROUP_LABELS=enums.CLIENT_AGE_GROUP_LABELS,
    LANGUAGE_PREFERRED_OPTIONS=enums.LANGUAGE_PREFERRED_OPTIONS,
    LANGUAGE_PREFERRED_LABELS=enums.LANGUAGE_PREFERRED_LABELS,
    INSURANCE_OPTIONS=enums.INSURANCE_OPTIONS,
    INSURANCE_LABELS=enums.INSURANCE_LABELS,
    DESIRED_TIME_SLOTS=enums.DESIRED_TIME_SLOTS,
    DESIRED_TIME_SLOT_LABELS=enums.DESIRED_TIME_SLOT_LABELS,
    DESIRED_TIME_DAYS=enums.DESIRED_TIME_DAYS,
    DESIRED_TIME_DAY_LABELS=enums.DESIRED_TIME_DAY_LABELS,
    DESIRED_TIME_PARTS=enums.DESIRED_TIME_PARTS,
    DESIRED_TIME_PART_LABELS=enums.DESIRED_TIME_PART_LABELS,
    CLIENT_REFERRAL_SERVICES=enums.CLIENT_REFERRAL_SERVICES,
    CLIENT_REFERRAL_SERVICE_LABELS=enums.CLIENT_REFERRAL_SERVICE_LABELS,
    TREATMENT_SETTINGS=enums.TREATMENT_SETTINGS,
    TREATMENT_SETTINGS_LABELS=enums.TREATMENT_SETTINGS_LABELS,
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
register_choice_labels(
    enums.LANGUAGE_PREFERRED_OPTIONS, enums.LANGUAGE_PREFERRED_LABELS
)
register_choice_labels(enums.INSURANCE_OPTIONS, enums.INSURANCE_LABELS)
register_choice_labels(
    enums.CLIENT_REFERRAL_SERVICES, enums.CLIENT_REFERRAL_SERVICE_LABELS
)
register_choice_labels(enums.TREATMENT_SETTINGS, enums.TREATMENT_SETTINGS_LABELS)
register_choice_labels(enums.LICENSE_TYPES, enums.LICENSE_TYPES_LABELS)
register_choice_labels(enums.EDUCATION_TYPES, enums.EDUCATION_TYPES_LABELS)
register_choice_labels(enums.CERTIFICATION_TYPES, enums.CERTIFICATION_TYPES_LABELS)

templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": "35729",
    }
