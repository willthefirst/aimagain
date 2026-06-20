"""Wire-schema coverage for the `SavedSearch` sub-resource.

Pins the create/update contract: `name` required + non-empty,
`filters` defaults to `{}`, unknown fields rejected (`extra="forbid"`),
and the PATCH at-least-one-field rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.domain.logic.saved_searches.schema import (
    SavedSearchCreate,
    SavedSearchRead,
    SavedSearchUpdate,
)


def test_create_defaults_filters_to_empty_object():
    payload = SavedSearchCreate(name="Openings")
    assert payload.filters == {}


def test_create_keeps_structured_filters():
    payload = SavedSearchCreate(
        name="CA openings", filters={"kind": "clinician_opening", "state": ["CA"]}
    )
    assert payload.filters == {"kind": "clinician_opening", "state": ["CA"]}


def test_create_requires_non_empty_name():
    with pytest.raises(ValidationError):
        SavedSearchCreate(name="")


def test_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        SavedSearchCreate(name="x", surprise="nope")


def test_update_allows_name_only():
    payload = SavedSearchUpdate(name="Renamed")
    assert payload.name == "Renamed"
    assert payload.filters is None  # leave unchanged


def test_update_allows_clearing_filters_to_empty():
    payload = SavedSearchUpdate(filters={})
    assert payload.filters == {}


def test_update_rejects_all_fields_absent():
    with pytest.raises(ValidationError):
        SavedSearchUpdate()


def test_read_projects_from_orm_attributes():
    now = datetime.now()
    row = type(
        "Row",
        (),
        {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "name": "Openings",
            "filters": {"kind": "clinician_opening"},
            "created_at": now,
            "updated_at": now,
        },
    )()
    read = SavedSearchRead.model_validate(row)
    assert read.name == "Openings"
    assert read.filters == {"kind": "clinician_opening"}
