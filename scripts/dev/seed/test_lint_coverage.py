"""Coverage for the seed drift lint's JSON-column rule.

Pins that a non-nullable JSON *object* column (default `dict`, e.g.
`saved_searches.filters`) is treated as covered — the generator seeds
it as `{}` — while a JSON *list* column still needs a
`JSON_LIST_SOURCE` entry (the list/dict distinction is what `dict`
defaults must not silently bypass).
"""

from __future__ import annotations

from scripts.dev.seed.lint_coverage import _json_default_is_object, main
from src.domain.models import Program, SavedSearch


def test_dict_default_json_column_is_object():
    assert _json_default_is_object(SavedSearch.__table__.c.filters) is True


def test_list_default_json_column_is_not_object():
    # A list-default JSON column must NOT register as an object — those
    # still flow through JSON_LIST_SOURCE.
    assert _json_default_is_object(Program.__table__.c.services) is False


def test_seed_coverage_has_no_drift():
    """The whole-schema drift check passes — `saved_searches.filters`
    (object column) doesn't trip the JSON rule."""
    assert main() == 0
