"""Entity-specific facts for the three clinician-credential subentities.

Universal invariants (identity field shapes, audit-type-matches-name,
audit-actions-derive-from-stem, template defaults, `to_resource_spec()`
round-trip) live in `test_spec_conformance.py` parametrized across
every entity. This file pins what's unique to the credential
subentities: the parent-chain identity, the parent-form redirect on
every mutation, and the audit-action-stem override (the entity's
`name` is `"clinician_licensure"` but the enum stem is `"LICENSURE"`).
"""

import pytest

from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.domain.specs.clinician_certification import CERTIFICATION_ENTITY
from src.domain.specs.clinician_education import EDUCATION_ENTITY
from src.domain.specs.clinician_licensure import LICENSURE_ENTITY

CREDENTIALS = [
    pytest.param(LICENSURE_ENTITY, "licensure", id="licensure"),
    pytest.param(EDUCATION_ENTITY, "education", id="education"),
    pytest.param(CERTIFICATION_ENTITY, "certification", id="certification"),
]


@pytest.mark.parametrize("entity,expected_stem", CREDENTIALS)
def test_audit_action_stem_overrides_name(entity, expected_stem):
    """Credentials' enum stems diverge from their `name` —
    `"clinician_licensure"` entity has actions `CREATE_LICENSURE`, etc.
    Conformance suite already proves the stem resolves to real enum
    members; this pins the specific override per credential."""
    assert entity.audit_action_stem == expected_stem


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_parent_is_clinician_entity(entity, _stem):
    """The parent chain is what `mount_entity`'s parent-id-walk + the
    generic `handle_create`/`handle_update` subentity branch read.
    Pinning identity here means the chain can't silently re-root."""
    assert entity.parent is CLINICIAN_ENTITY


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_redirects_target_sub_resource_list(entity, _stem):
    """Sub-row mutations send HTMX clients back to the sub-resource's
    own list page — the page the user is already on after #1336 promoted
    each credential into its own dedicated /clinicians/{id}/<sub> route.
    The list page is the canonical "stay where you were" target now that
    the clinician edit form is person-level only."""
    target = f"/clinicians/abc-123/{entity.url_collection}"
    assert entity.create_redirect(clinician_id="abc-123") == target
    assert entity.update_redirect(clinician_id="abc-123") == target
    assert entity.delete_redirect(clinician_id="abc-123") == target


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_form_pages_point_at_subresource_view_templates(entity, _stem):
    """Each credential's create/edit form template points at the
    framework's spec-driven sub-resource view chrome (which renders
    `templates.form_partial` inside the standard form-page wrapper)
    rather than a per-entity ``<collection>/form_{new,edit}.html``
    wrapper file. The convention-default would have set those to
    ``"<collection>/form_new.html"`` — the assertion catches a future
    regression where the credential factory accidentally goes back to
    requiring per-entity wrappers."""
    assert entity.templates.form_new == "views/subresource_form_new.html"
    assert entity.templates.form_edit == "views/subresource_form_edit.html"


@pytest.mark.parametrize("entity,_stem", CREDENTIALS)
def test_form_partial_points_at_the_per_entity_partial(entity, _stem):
    """The credential factory threads `form_partial` through into
    `templates.form_partial` — the path that `views/subresource_form_*`
    `{% include %}`s at render time. Pinning the value here catches a
    regression where the factory drops it (e.g. the
    `__post_init__` rebuild skipping the field again)."""
    expected = f"{entity.url_collection}/_form_{_stem}.html"
    assert entity.templates.form_partial == expected
