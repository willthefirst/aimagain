import os

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models import post_enums

auto_reload = os.getenv("ENVIRONMENT", "development") == "development"

_env = Environment(
    loader=FileSystemLoader("src/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

# Expose the controlled-vocabulary tuples (and matching display-label
# dicts) from `src/models/post_enums.py` as Jinja globals so per-kind
# form templates iterate over the same values that the schema's
# `Literal[*TUPLE]`s and the DB CHECK constraints render from. Adding a
# value to a tuple in `post_enums.py` then shows up everywhere — schema,
# DB, and form dropdown — without per-template edits. The label dicts
# are looked up in the form-render macro
# (`src/templates/posts/_form_macros.html`); the
# `test_labels_cover_their_tuples` guardrail asserts every value in a
# tuple has a label.
_env.globals.update(
    US_STATES=post_enums.US_STATES,
    LOCATION_AVAILABILITY_OPTIONS=post_enums.LOCATION_AVAILABILITY_OPTIONS,
    LOCATION_AVAILABILITY_LABELS=post_enums.LOCATION_AVAILABILITY_LABELS,
    CLIENT_AGE_GROUPS=post_enums.CLIENT_AGE_GROUPS,
    CLIENT_AGE_GROUP_LABELS=post_enums.CLIENT_AGE_GROUP_LABELS,
    LANGUAGE_PREFERRED_OPTIONS=post_enums.LANGUAGE_PREFERRED_OPTIONS,
    LANGUAGE_PREFERRED_LABELS=post_enums.LANGUAGE_PREFERRED_LABELS,
    INSURANCE_OPTIONS=post_enums.INSURANCE_OPTIONS,
    INSURANCE_LABELS=post_enums.INSURANCE_LABELS,
)

templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context with environment information."""
    return {
        "is_development": os.getenv("ENVIRONMENT", "development") == "development",
        "livereload_port": os.getenv("LIVERELOAD_PORT", "35729"),
    }
