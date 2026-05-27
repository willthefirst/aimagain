"""Entity-specific facts for the three clinician-credential subentities.

Universal invariants (identity field shapes, audit-type-matches-name,
audit-actions-derive-from-stem, template defaults, `to_resource_spec()`
round-trip) live in `test_spec_conformance.py` parametrized across
every entity. This file pins what's unique to the credential
subentities: the parent-chain identity, the parent-form redirect on
every mutation, and the audit-action-stem override (the entity's
`name` is `"provider_licensure"` but the enum stem is `"LICENSURE"`).
"""

import pytest

from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY

CREDENTIALS = [
    pytest.param(LICENSURE_ENTITY, "licensure", id="licensure"),
    pytest.param(EDUCATION_ENTITY, "education", id="education"),
    pytest.param(CERTIFICATION_ENTITY, "certification", id="certification"),
]


@pytest.mark.parametrize("entity,expected_stem", CREDENTIALS)
def test_audit_action_stem_overrides_name(entity, expected_stem):
    """Credentials' enum stems diverge from their `name` —
    `"provider_licensure"` entity has actions `CREATE_LICENSURE`, etc.
    Conformance suite already proves the stem resolves to real enum
    members; this pins the specific override per credential."""
    assert entity.audit_action_stem == expected_stem


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_parent_is_provider_entity(entity, _stem):
    """The parent chain is what `mount_entity`'s parent-id-walk + the
    generic `handle_create`/`handle_update` subentity branch read.
    Pinning identity here means the chain can't silently re-root."""
    assert entity.parent is CLINICIAN_ENTITY


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_redirects_target_parent_form(entity, _stem):
    """Sub-row mutations send HTMX clients back to the parent edit form
    — the user keeps editing the parent clinician entry after each
    credential write. After #642 PR 4 the URL family is
    `/clinicians/{clinician_id}/...`; the Python model class stays
    `Clinician`."""
    target = "/clinicians/abc-123/form"
    assert entity.create_redirect(clinician_id="abc-123") == target
    assert entity.update_redirect(clinician_id="abc-123") == target
    assert entity.delete_redirect(clinician_id="abc-123") == target
