"""View helpers for clinicians — pure functions consumed by templates.

`clinician_card_view(clinician)` is the unified view-model the detail
page reads from, mirroring the pattern set by
`src.domain.logic.posts.view.post_card_view`. The function collapses
field references that templates would otherwise have to dereference
(`clinician.org.name`, the multi-conditional insurance phrase) into one
flat dict so the template doesn't carry display logic.

Exposed as a Jinja global via `src/domain/template_globals.py`.
"""

from typing import Any

from src.framework.rendering.address import full_address


def _role_attr(clinician, attr, default=None):
    """Source a per-role attribute from `clinician.primary_affiliation`.

    Falls through to the attribute on the clinician directly for test stubs
    that set fields on a `SimpleNamespace` without wiring an affiliation.
    """
    affiliation = getattr(clinician, "primary_affiliation", None)
    if affiliation is not None:
        return getattr(affiliation, attr, default)
    return getattr(clinician, attr, default)


def _insurance_summary(clinician) -> str:
    """Compose a single-string insurance phrase that unions a Clinician's
    insurance posture across **every** affiliation it holds.

    After #642 PR 3 the directory listing shows one row per Clinician that
    reflects all affiliations (not just the primary). The Insurance cell
    reads this phrase, so the summary unions across rows:

      - ``in_network_carriers``: union of carrier codes across all
        affiliations (first-seen order preserved, deduped).
      - ``accepts_out_of_network``: ``True`` if **any** affiliation
        accepts OON.
      - ``sliding_scale``: ``True`` if **any** affiliation offers sliding
        scale — surfaces in the row as a trailing ``"· sliding"`` so
        callers don't need to render it as a separate badge.

    Returns one of:
      - ``"In-network (Aetna, Anthem / BCBS) · Out-of-network · sliding"``
      - ``"In-network (Aetna) · sliding"``
      - ``"Out-of-network"``
      - ``"Self-pay only"``  (no carriers, no OON anywhere)

    Falls back to the legacy single-record path (``_role_attr``) when
    ``clinician.affiliations`` is empty/absent — covers ``SimpleNamespace``
    test stubs that don't wire the 1:N relationship.

    Display-label lookup
    (:data:`src.domain.models.enums.INSURANCE_CARRIER_LABELS`) happens
    here so the template doesn't need to know about it. Importing the
    label dict at module top would close a cluster-boundary import
    chain back into `models`; deferring to call time keeps the
    dependency graph quiet.
    """
    from src.domain.models.enums import INSURANCE_CARRIER_LABELS

    affiliations = list(getattr(clinician, "affiliations", None) or [])
    if affiliations:
        carriers: list[str] = []
        seen: set[str] = set()
        for aff in affiliations:
            for c in list(getattr(aff, "in_network_carriers", None) or []):
                if c not in seen:
                    seen.add(c)
                    carriers.append(c)
        accepts_oon = any(
            bool(getattr(aff, "accepts_out_of_network", False)) for aff in affiliations
        )
        sliding = any(
            bool(getattr(aff, "sliding_scale", False)) for aff in affiliations
        )
    else:
        # No affiliations — fall through to the clinician directly for
        # test stubs that set the columns on a SimpleNamespace.
        carriers = list(_role_attr(clinician, "in_network_carriers", []) or [])
        accepts_oon = bool(_role_attr(clinician, "accepts_out_of_network", False))
        sliding = bool(_role_attr(clinician, "sliding_scale", False))

    parts: list[str] = []
    if carriers:
        labels = ", ".join(INSURANCE_CARRIER_LABELS[c] for c in carriers)
        parts.append(f"In-network ({labels})")
    if accepts_oon:
        parts.append("Out-of-network")
    if not parts:
        base = "Self-pay only"
    else:
        base = " · ".join(parts)
    if sliding:
        base = f"{base} · sliding"
    return base


def _affiliation_insurance_summary(affiliation) -> str:
    """Same shape as :func:`_insurance_summary` but sourced directly
    from an ``Affiliation`` (not a ``Clinician``). The detail page's
    stacked-sections layout (#642 PR 2) renders one insurance line per
    affiliation, so we need a per-affiliation summarizer alongside the
    per-clinician one the directory listing still uses."""
    from src.domain.models.enums import INSURANCE_CARRIER_LABELS

    carriers = list(getattr(affiliation, "in_network_carriers", None) or [])
    accepts_oon = bool(getattr(affiliation, "accepts_out_of_network", False))
    if not carriers and not accepts_oon:
        return "Self-pay only"
    parts: list[str] = []
    if carriers:
        labels = ", ".join(INSURANCE_CARRIER_LABELS[c] for c in carriers)
        parts.append(f"In-network ({labels})")
    if accepts_oon:
        parts.append("Out-of-network")
    return " · ".join(parts)


def affiliation_card_view(affiliation, org=None) -> dict[str, Any]:
    """Normalize a single ``Affiliation`` into the per-role dict shape
    one stacked-section card on the clinician detail page reads from
    (#642 PR 2).

    Mirrors the per-role keys ``clinician_card_view`` exposes at the top
    level (``full_address``, ``in_person_label``, ``virtual_label``,
    ``insurance_summary``, ``sliding_scale_label``, ``cost``) so the
    template's "one card per affiliation" loop reads the same flat
    dict shape it has always read — only now once per row.

    ``org`` defaults to ``affiliation.org``; callers can override (e.g.
    test stubs that don't wire the relationship).

    Returns:
        org_id / org_name / org_url: identity of the practice this
            affiliation belongs to (heading of the card).
        full_address: ``"City, ST ZIP"`` composed from the affiliation's
            ``LocationMixin`` columns. ``None`` if every part is empty.
        in_person_label / virtual_label: display labels for the
            ``location_availability`` enum values.
        insurance_summary: per-affiliation insurance phrase.
        sliding_scale_label: ``"Yes"`` or ``"No"``.
        cost: pass-through optional free-text.
    """
    from src.domain.models.enums import LOCATION_AVAILABILITY_LABELS

    if org is None:
        org = getattr(affiliation, "org", None)
    org_id = getattr(affiliation, "org_id", None)
    return {
        "org_id": org_id,
        "org_name": (getattr(org, "name", None) if org else None),
        "org_url": (f"/organizations/{org_id}" if org_id is not None else None),
        "full_address": full_address(
            getattr(affiliation, "location_city", None),
            getattr(affiliation, "location_state", None),
            getattr(affiliation, "location_zip", None),
        ),
        "in_person_label": LOCATION_AVAILABILITY_LABELS.get(
            getattr(affiliation, "in_person_sessions", None) or ""
        ),
        "virtual_label": LOCATION_AVAILABILITY_LABELS.get(
            getattr(affiliation, "virtual_sessions", None) or ""
        ),
        "insurance_summary": _affiliation_insurance_summary(affiliation),
        "sliding_scale_label": (
            "Yes" if getattr(affiliation, "sliding_scale", False) else "No"
        ),
        "cost": getattr(affiliation, "cost", None),
    }


def clinician_card_view(clinician) -> dict[str, Any]:
    """Normalize a `Clinician` row into the flat shape
    ``clinicians/detail.html`` reads from.

    Returns a dict so Jinja's ``view.field`` attribute syntax works
    (Jinja resolves attribute access to ``__getitem__`` on dicts).
    Missing values come back as ``None`` so templates render via
    ``{% if view.x %}`` without extra nullability handling. Display-
    label lookup happens here (one path); the template iterates over
    pre-resolved strings.

    Returns:
        practice_name: ``clinician.org.name`` (the practice's display
            name — the *primary* affiliation's org). Mirrored as
            ``affiliations[0].org_name`` for non-detail callers.
        practice_url: ``/organizations/<org_id>`` link to the parent
            Organization — preserves the cross-resource navigation
            the old template emitted inline.
        full_address: ``"City, ST ZIP"`` composed from the primary
            affiliation's ``LocationMixin`` columns. ``None`` if every
            part is empty.
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
        affiliations: list of per-affiliation dicts (one per row in
            ``clinician.affiliations``) shaped by
            :func:`affiliation_card_view`. The detail page renders one
            stacked card per entry.
    """
    from src.domain.models.enums import LOCATION_AVAILABILITY_LABELS

    org = getattr(clinician, "org", None)
    org_id = _role_attr(clinician, "org_id")
    affiliations = list(getattr(clinician, "affiliations", None) or [])
    return {
        "practice_name": (getattr(org, "name", None) if org else None),
        "practice_url": (f"/organizations/{org_id}" if org_id is not None else None),
        "full_address": full_address(
            _role_attr(clinician, "location_city"),
            _role_attr(clinician, "location_state"),
            _role_attr(clinician, "location_zip"),
        ),
        "in_person_label": LOCATION_AVAILABILITY_LABELS.get(
            _role_attr(clinician, "in_person_sessions") or ""
        ),
        "virtual_label": LOCATION_AVAILABILITY_LABELS.get(
            _role_attr(clinician, "virtual_sessions") or ""
        ),
        "insurance_summary": _insurance_summary(clinician),
        "sliding_scale_label": (
            "Yes" if _role_attr(clinician, "sliding_scale", False) else "No"
        ),
        "cost": _role_attr(clinician, "cost"),
        "npi": getattr(clinician, "npi", None),
        "licensures": list(getattr(clinician, "licensures", None) or []),
        "educations": list(getattr(clinician, "educations", None) or []),
        "certifications": list(getattr(clinician, "certifications", None) or []),
        "affiliations": [
            affiliation_card_view(aff, getattr(aff, "org", None))
            for aff in affiliations
        ],
    }
