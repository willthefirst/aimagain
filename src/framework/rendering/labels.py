"""Single source of truth for chrome-facing entity labels.

Every "Create X" string in the app — the form-page H1, the list-page
toolbar button, the chrome nav CTA, the polymorphic kind-picker
options — funnels through `entity_create_label` here. Calling the
same function from the handler (which sets the H1 context var) and
from each template's CTA is the structural enforcement that the two
strings stay in lockstep; the colocated test
`test_create_h1_matches_cta_label` renders every form_new page and
pins the equivalence.

The helper is also exposed as a Jinja global by
`src/framework/rendering/templating.py` so templates write
``{{ entity_create_label('opening') }}`` instead of hardcoding the
string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.framework.dispatch.registry import entity_registry

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


def _spec_by_name(name: str) -> "EntitySpec":
    """Resolve an entity name to its registered spec. Duplicates the
    helper in `route_urls.py` because importing across rendering helpers
    would close a cycle; the helper is one-liner."""
    for spec in entity_registry.specs():
        if spec.name == name:
            return spec
    known = sorted(s.name for s in entity_registry.specs())
    raise ValueError(
        f"Unknown entity name {name!r}. Known entities: {known}. "
        "Entity names are singular (e.g. 'organization', not 'organizations')."
    )


def entity_create_label(name: str, *, kind: str | None = None) -> str:
    """Return the canonical "Create <noun>" string for an entity.

    Resolution order:

      1. ``kind`` supplied and the spec carries a `discriminator` →
         use the registry's per-kind ``list_label`` (e.g. ``"clinician
         opening"``, ``"program intake"``, ``"client referral"``). The
         result is ``"Create clinician opening"``.
      2. The spec is kind-locked (``discriminator_value`` set) → use
         the bound kind's ``list_label``. So ``/referrals`` always
         renders ``"Create client referral"`` regardless of what the
         caller passes.
      3. Otherwise → ``"Create " + spec.singular_label`` (the default
         path for non-polymorphic entities and for the subset-supertype
         picker page).

    The function lowercases the noun so CTAs and H1s read in the same
    "sentence-fragment" style — title-casing happens via CSS where
    needed, never in the string itself.
    """
    spec = _spec_by_name(name)
    return create_label_for(spec, kind=kind)


def entity_edit_label(name: str, *, kind: str | None = None) -> str:
    """Return the canonical "Edit <noun>" string for an entity.

    Mirrors `entity_create_label`'s resolution rule — same per-kind
    `list_label` lookup so the edit page's H1 reads "Edit clinician
    opening" / "Edit program intake" / "Edit client referral" / "Edit
    organization" rather than the row's identity string ("Edit Adult
    male (25-64)" was the friction this funnel fixes). The row
    identity stays on the breadcrumb's middle segment via the
    template's `current_label` block.
    """
    spec = _spec_by_name(name)
    return edit_label_for(spec, kind=kind)


def entity_filter_label(name: str) -> str:
    """Return the canonical "Filter <plural>" string for an entity.

    Mirrors `entity_create_label`: the dedicated filter page's H1 and
    the list-page toolbar's filter link both call this so the button
    text and the page title can't drift. Uses the spec's
    ``url_collection`` (already plural, lowercase) — e.g.
    ``"Filter clinicians"``, ``"Filter openings"``.
    """
    spec = _spec_by_name(name)
    return filter_label_for(spec)


def create_label_for(spec: "EntitySpec", *, kind: str | None = None) -> str:
    """Spec-direct form of `entity_create_label` — same resolution rule.

    Used by `handle_get_new_form` which already holds the spec and
    shouldn't round-trip through the registry (test specs aren't
    registered). See `entity_create_label` for the rule.
    """
    return f"Create {_noun_for(spec, kind=kind)}"


def edit_label_for(spec: "EntitySpec", *, kind: str | None = None) -> str:
    """Spec-direct form of `entity_edit_label` — same resolution rule.

    Used by `handle_get_edit_form` which already holds the spec and
    derives `kind` from the loaded target row when the spec is
    polymorphic. See `entity_edit_label` for the rule.
    """
    return f"Edit {_noun_for(spec, kind=kind)}"


def filter_label_for(spec: "EntitySpec") -> str:
    """Spec-direct form of `entity_filter_label`. See its docstring."""
    return f"Filter {spec.url_collection}"


def _noun_for(spec: "EntitySpec", *, kind: str | None) -> str:
    """Pick the per-call noun for the entity / optional kind pair.

    Split out so the handler (`handle_get_new_form`) can build the
    same `"Create <noun>"` string the template would, without
    duplicating the resolution rules. See `entity_create_label`
    docstring for the rule.
    """
    if spec.discriminator is not None:
        # Kind-locked face: the bound discriminator_value wins even when
        # the caller doesn't pass `kind`, so `/referrals/form` always
        # reads "Create client referral" (matches the picker option on
        # the umbrella page). `getattr` lets test specs use a minimal
        # registry kind type without a `list_label` attribute and still
        # round-trip through the helper.
        effective_kind = kind or spec.discriminator_value
        if effective_kind is not None and effective_kind in spec.discriminator:
            kind_spec = spec.discriminator[effective_kind]
            label = getattr(kind_spec, "list_label", None)
            if label:
                return label
    return spec.singular_label
