"""View helpers for providers — pure functions consumed by templates.

`provider_card_view(provider)` is the unified view-model the detail
page reads from, mirroring the pattern set by
`src.domain.logic.posts.view.post_card_view`. The function collapses
field references that templates would otherwise have to dereference
(`provider.org.name`, the multi-conditional insurance phrase) into one
flat dict so the template doesn't carry display logic.

Exposed as a Jinja global via `src/domain/template_globals.py`.
"""

from typing import Any


def _full_address(
    city: str | None, state: str | None, zip_code: str | None
) -> str | None:
    """Compose ``"City, ST ZIP"`` from the three location columns.

    Returns ``None`` when every part is empty so templates can ``{% if
    view.full_address %}`` rather than render a blank row. Mirrors
    :func:`src.domain.logic.posts.view._full_address` — kept separate
    because the providers logic module should not import from the posts
    logic module (cross-cluster boundary)."""
    if not any((city, state, zip_code)):
        return None
    head = ", ".join(p for p in (city, state) if p)
    if zip_code:
        return f"{head} {zip_code}" if head else zip_code
    return head or None


def _insurance_summary(provider) -> str:
    """Compose a single-string insurance phrase from the provider's
    in-network / out-of-network / self-pay posture.

    Returns one of:
      - ``"In-network (Aetna, BCBS) · Out-of-network"``  (both)
      - ``"In-network (Aetna)"``                         (in-network only)
      - ``"Out-of-network"``                             (oon only)
      - ``"Self-pay only"``                              (neither)

    Collapses the three nested conditionals the old detail template
    inlined; the template now reads a single ``view.insurance_summary``
    string. The display-label lookup
    (:data:`src.domain.models.enums.INSURANCE_CARRIER_LABELS`) happens
    here so the template doesn't need to know about it. Importing the
    label dict at module top would close a cluster-boundary import
    chain back into `models`; deferring to call time keeps the
    dependency graph quiet."""
    from src.domain.models.enums import INSURANCE_CARRIER_LABELS

    carriers = list(getattr(provider, "in_network_carriers", None) or [])
    accepts_oon = bool(getattr(provider, "accepts_out_of_network", False))
    if not carriers and not accepts_oon:
        return "Self-pay only"
    parts: list[str] = []
    if carriers:
        labels = ", ".join(INSURANCE_CARRIER_LABELS[c] for c in carriers)
        parts.append(f"In-network ({labels})")
    if accepts_oon:
        parts.append("Out-of-network")
    return " · ".join(parts)


def provider_card_view(provider) -> dict[str, Any]:
    """Normalize a `Provider` row into the flat shape
    ``providers/detail.html`` reads from.

    Returns a dict so Jinja's ``view.field`` attribute syntax works
    (Jinja resolves attribute access to ``__getitem__`` on dicts).
    Missing values come back as ``None`` so templates render via
    ``{% if view.x %}`` without extra nullability handling. Display-
    label lookup happens here (one path); the template iterates over
    pre-resolved strings.

    Returns:
        practice_name: ``provider.org.name`` (the practice's display
            name).
        practice_url: ``/organizations/<org_id>`` link to the parent
            Organization — preserves the cross-resource navigation
            the old template emitted inline.
        full_address: ``"City, ST ZIP"`` composed from
            ``LocationMixin`` columns. ``None`` if every part is empty.
        in_person_label / virtual_label: display labels for the
            ``location_availability`` enum values
            (``in_person_sessions`` / ``virtual_sessions``).
        insurance_summary: one-string phrase covering the in-network /
            out-of-network / self-pay posture — see
            :func:`_insurance_summary`.
        sliding_scale_label: ``"Yes"`` or ``"No"``.
        cost: pass-through optional free-text.
        npi: pass-through optional 10-digit NPI.
        licensures / educations / certifications: pass-through ORM
            collections (the template iterates them via the existing
            ``credential_row`` partial; no shape change).
    """
    from src.domain.models.enums import LOCATION_AVAILABILITY_LABELS

    org = getattr(provider, "org", None)
    # `npi` moved to `clinicians.npi` in #629 PR 1 — read through the
    # `provider.clinician` relationship (NOT NULL since the same PR).
    clinician = getattr(provider, "clinician", None)
    return {
        "practice_name": (getattr(org, "name", None) if org else None),
        "practice_url": (
            f"/organizations/{provider.org_id}"
            if getattr(provider, "org_id", None) is not None
            else None
        ),
        "full_address": _full_address(
            getattr(provider, "location_city", None),
            getattr(provider, "location_state", None),
            getattr(provider, "location_zip", None),
        ),
        "in_person_label": LOCATION_AVAILABILITY_LABELS.get(
            getattr(provider, "in_person_sessions", None) or ""
        ),
        "virtual_label": LOCATION_AVAILABILITY_LABELS.get(
            getattr(provider, "virtual_sessions", None) or ""
        ),
        "insurance_summary": _insurance_summary(provider),
        "sliding_scale_label": (
            "Yes" if getattr(provider, "sliding_scale", False) else "No"
        ),
        "cost": getattr(provider, "cost", None),
        "npi": getattr(clinician, "npi", None) if clinician is not None else None,
        "licensures": list(getattr(provider, "licensures", None) or []),
        "educations": list(getattr(provider, "educations", None) or []),
        "certifications": list(getattr(provider, "certifications", None) or []),
    }
