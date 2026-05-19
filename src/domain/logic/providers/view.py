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


def _role_attr(provider, attr, default=None):
    """Source a per-role attribute from `provider.affiliation` first,
    falling back to the legacy column on `provider` itself.

    The PR 2 migration populates ``provider.affiliation`` with a
    1:1 mirror of the per-role columns currently still on
    ``providers``; PR 3 switches the directory's read path here.
    PR 4 will drop the duplicated columns from ``providers`` and
    this helper's fallback path with them.

    Test stubs typed as `SimpleNamespace` may set the legacy attr
    without an affiliation — the fallback keeps those passing
    until PR 4 retires the legacy field set.
    """
    affiliation = getattr(provider, "affiliation", None)
    if affiliation is not None and getattr(affiliation, attr, None) is not None:
        return getattr(affiliation, attr)
    return getattr(provider, attr, default)


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
    dependency graph quiet.

    Reads source from ``provider.affiliation`` first, falling back
    to the legacy columns on ``provider`` itself (#629 PR 3).
    """
    from src.domain.models.enums import INSURANCE_CARRIER_LABELS

    carriers = list(_role_attr(provider, "in_network_carriers", []) or [])
    accepts_oon = bool(_role_attr(provider, "accepts_out_of_network", False))
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
    # Per-role attrs come from `provider.affiliation` after #629 PR 3 —
    # the directory's source-of-truth for "what is this clinician's
    # role at this org." `npi` continues to come from
    # `provider.clinician` (PR 1). Legacy columns on `providers` are
    # the PR-2-era mirror and `_role_attr` falls back to them when
    # affiliation is absent (test stubs); PR 4 drops both the columns
    # and the fallback.
    clinician = getattr(provider, "clinician", None)
    return {
        "practice_name": (getattr(org, "name", None) if org else None),
        "practice_url": (
            f"/organizations/{provider.org_id}"
            if getattr(provider, "org_id", None) is not None
            else None
        ),
        "full_address": _full_address(
            _role_attr(provider, "location_city"),
            _role_attr(provider, "location_state"),
            _role_attr(provider, "location_zip"),
        ),
        "in_person_label": LOCATION_AVAILABILITY_LABELS.get(
            _role_attr(provider, "in_person_sessions") or ""
        ),
        "virtual_label": LOCATION_AVAILABILITY_LABELS.get(
            _role_attr(provider, "virtual_sessions") or ""
        ),
        "insurance_summary": _insurance_summary(provider),
        "sliding_scale_label": (
            "Yes" if _role_attr(provider, "sliding_scale", False) else "No"
        ),
        "cost": _role_attr(provider, "cost"),
        "npi": getattr(clinician, "npi", None) if clinician is not None else None,
        "licensures": list(getattr(provider, "licensures", None) or []),
        "educations": list(getattr(provider, "educations", None) or []),
        "certifications": list(getattr(provider, "certifications", None) or []),
    }
