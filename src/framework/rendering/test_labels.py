"""Pin tests for the chrome-label helpers in `labels.py`.

The helpers are the single source of truth for every "Create X" /
"Filter X" string in the app. The tests below pin two things:

  1. The label-resolution rules (the unit shape of the helpers).
  2. The structural pin: every concrete `EntitySpec` in
     `src.domain.specs.ALL_ENTITY_SPECS` resolves to a non-empty
     label via the helpers. If a future spec lands without a
     `singular_label` or without a `discriminator`-backed
     `list_label`, this test fails at import time of the suite.
"""

from __future__ import annotations

import pytest

from src.framework.rendering.labels import (
    create_label_for,
    edit_label_for,
    entity_create_label,
    entity_edit_label,
    entity_filter_label,
    filter_label_for,
)


def test_create_label_uses_singular_label_for_non_polymorphic_spec():
    from src.domain.specs.organization import ORGANIZATION_ENTITY

    assert create_label_for(ORGANIZATION_ENTITY) == "Create organization"


def test_create_label_uses_per_kind_list_label_when_kind_supplied():
    """Whole-supertype face (`/posts`) renders the per-kind noun when
    `kind=` is passed — what the picker option labels and the
    kind-specific form pages both call."""
    from src.domain.specs.posts import POST_ENTITY

    assert create_label_for(POST_ENTITY, kind="referral") == "Create client referral"
    assert (
        create_label_for(POST_ENTITY, kind="clinician_opening")
        == "Create clinician opening"
    )
    assert (
        create_label_for(POST_ENTITY, kind="program_intake") == "Create program intake"
    )


def test_create_label_whole_supertype_no_kind_falls_back_to_singular():
    """The umbrella `/posts/form` picker page (no `?kind=`) reads
    `entity_create_label('post')` → ``"Create post"``. Same string the
    list-page toolbar CTA uses."""
    from src.domain.specs.posts import POST_ENTITY

    assert create_label_for(POST_ENTITY) == "Create post"


def test_edit_label_uses_singular_label_for_non_polymorphic_spec():
    from src.domain.specs.organization import ORGANIZATION_ENTITY

    assert edit_label_for(ORGANIZATION_ENTITY) == "Edit organization"


def test_edit_label_uses_per_kind_list_label_when_kind_supplied():
    """The edit page for a whole-supertype face's row reads the row's
    stored kind off the loaded target — `handle_get_edit_form` derives
    this and passes it as `kind=`. Same per-kind noun the create page
    uses for the matching form."""
    from src.domain.specs.posts import POST_ENTITY

    assert edit_label_for(POST_ENTITY, kind="referral") == "Edit client referral"
    assert (
        edit_label_for(POST_ENTITY, kind="clinician_opening")
        == "Edit clinician opening"
    )
    assert edit_label_for(POST_ENTITY, kind="program_intake") == "Edit program intake"


def test_filter_label_uses_url_collection():
    from src.domain.specs.clinician import CLINICIAN_ENTITY

    assert filter_label_for(CLINICIAN_ENTITY) == "Filter clinicians"


# --- Registry-driven structural pins -----------------------------------


def test_every_registry_spec_resolves_via_entity_create_label():
    """Round-trip each registered spec through the public Jinja-global
    helper so a future spec that fails to populate `singular_label` or
    diverges from the registry surfaces as a unit-test failure rather
    than as a stray "Create None" string in the UI."""
    from src.framework.dispatch.registry import entity_registry

    for spec in entity_registry.specs():
        label = entity_create_label(spec.name)
        assert label.startswith("Create ")
        # The noun half is non-empty — guards against a spec landing
        # with `singular_label=""` (would render "Create ").
        assert len(label) > len("Create ")


def test_every_registry_spec_resolves_via_entity_edit_label():
    """Mirror of the create-label round-trip — every registered spec
    produces a sensible "Edit <noun>" string."""
    from src.framework.dispatch.registry import entity_registry

    for spec in entity_registry.specs():
        label = entity_edit_label(spec.name)
        assert label.startswith("Edit ")
        assert len(label) > len("Edit ")


def test_every_searchable_spec_resolves_via_entity_filter_label():
    from src.framework.dispatch.registry import entity_registry

    for spec in entity_registry.specs():
        if not spec.declared_filters:
            continue
        label = entity_filter_label(spec.name)
        assert label.startswith("Filter ")
        assert len(label) > len("Filter ")


def test_entity_create_label_unknown_name_raises_with_known_names():
    """Typos in template literal entity names fail loud at render
    time with the list of known names — same shape `entity_url`
    uses."""
    with pytest.raises(ValueError, match="Unknown entity name"):
        entity_create_label("clinicianz")
