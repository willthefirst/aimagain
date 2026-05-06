"""Controlled-vocabulary tuples for per-kind detail columns.

Single source of truth for the small enums that the per-kind
`*_details` tables use as `Text` + CHECK columns. Lives in its own
module so the detail models can depend on it without dragging in the
parent `Post` / `post_kinds` registry (which depends on the detail
models in turn — a leaf module breaks that cycle).

The schema layer's `Literal[*TUPLE]` types are derived from the same
tuples; the guardrail test `test_schema_literals_match_model_tuples`
(in `src/schemas/test_post.py`) keeps them in lockstep. See
[`../../notes/forms_spec.md`](../../notes/forms_spec.md) for the form
spec these vocabularies feed.
"""

from typing import Final

US_STATES: Final[tuple[str, ...]] = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
)
LOCATION_AVAILABILITY_OPTIONS: Final[tuple[str, ...]] = (
    "yes",
    "no",
    "please_contact",
)
CLIENT_AGE_GROUPS: Final[tuple[str, ...]] = (
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
)
LANGUAGE_PREFERRED_OPTIONS: Final[tuple[str, ...]] = ("no", "yes")
INSURANCE_OPTIONS: Final[tuple[str, ...]] = (
    "in_network",
    "out_of_network",
    "in_and_out_of_network",
)


def check_in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    """SQL fragment for a `column IN (...)` CHECK constraint, rendered
    from a tuple. Used by per-kind detail tables so the DB-level
    vocabulary stays in lockstep with the Python tuples above. Mirrors
    the `kind_check_sql()` pattern used by the parent `posts` table."""
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"
