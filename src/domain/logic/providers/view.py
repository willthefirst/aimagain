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

from src.framework.rendering.address import full_address


def _role_attr(provider, attr, default=None):
    """Source a per-role attribute from `provider.primary_affiliation`.

    Post-#635 PR B the per-role columns no longer live on `providers` —
    affiliation is the single source of truth. After #642 PR 1 a
    Provider may hold multiple Affiliations; the directory listing and
    the post-opening dropdown read through the primary one (oldest by
    `created_at`). The `Provider` ORM class surfaces `provider.location_city`
    etc. as `@property` proxies over `primary_affiliation`, but
    `provider_card_view` also accepts test stubs that set fields on a
    `SimpleNamespace` without wiring an affiliation; for those, fall
    through to the attribute on the provider directly (the property
    proxies live on the real ORM class, not the stub).
    """
    affiliation = getattr(provider, "primary_affiliation", None)
    if affiliation is not None:
        return getattr(affiliation, attr, default)
    return getattr(provider, attr, default)


def _insurance_summary(provider) -> str:
    """Compose a single-string insurance phrase that unions a Provider's
    insurance posture across **every** affiliation it holds.

    After #642 PR 3 the directory listing shows one row per Provider that
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
    ``provider.affiliations`` is empty/absent — covers ``SimpleNamespace``
    test stubs that don't wire the 1:N relationship.

    Display-label lookup
    (:data:`src.domain.models.enums.INSURANCE_CARRIER_LABELS`) happens
    here so the template doesn't need to know about it. Importing the
    label dict at module top would close a cluster-boundary import
    chain back into `models`; deferring to call time keeps the
    dependency graph quiet.
    """
    from src.domain.models.enums import INSURANCE_CARRIER_LABELS

    affiliations = list(getattr(provider, "affiliations", None) or [])
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
        # No affiliations on the row — fall through to the legacy
        # single-record path so test stubs that set the columns on the
        # provider stub (or via `primary_affiliation`) keep working.
        carriers = list(_role_attr(provider, "in_network_carriers", []) or [])
        accepts_oon = bool(_role_attr(provider, "accepts_out_of_network", False))
        sliding = bool(_role_attr(provider, "sliding_scale", False))

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
    from an ``Affiliation`` (not a ``Provider``). The detail page's
    stacked-sections layout (#642 PR 2) renders one insurance line per
    affiliation, so we need a per-affiliation summarizer alongside the
    per-provider one the directory listing still uses."""
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
    one stacked-section card on the provider detail page reads from
    (#642 PR 2).

    Mirrors the per-role keys ``provider_card_view`` exposes at the top
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
            ``credential_row`` partial; no shape change). These are
            clinician-level (FK to ``clinicians.id`` after #635 PR A)
            and render once on the detail page, not per-affiliation.
        affiliations: list of per-affiliation dicts (one per row in
            ``provider.affiliations``) shaped by
            :func:`affiliation_card_view`. The detail page renders one
            stacked card per entry (#642 PR 2). The flat per-role keys
            above still read off ``provider.primary_affiliation`` so
            the directory listing and other non-detail callers don't
            break.
    """
    from src.domain.models.enums import LOCATION_AVAILABILITY_LABELS

    org = getattr(provider, "org", None)
    # Per-role attrs come from `provider.primary_affiliation` — the
    # directory's source-of-truth for "what is this clinician's role
    # at this org" after #635 PR B dropped the duplicated columns from
    # `providers`. After #642 PR 1, a Provider may hold multiple
    # Affiliations; the listing reads through the primary (oldest)
    # one — PR 3 swaps the listing to one row per Clinician with
    # stacked affiliations. PR 2 (this PR) adds the `affiliations`
    # list below so the *detail* page renders one card per
    # affiliation while the directory listing's read path stays
    # unchanged.
    # `npi` continues to come from `provider.clinician` (#629 PR 1).
    # `_role_attr` still falls back to attributes on the `provider`
    # object itself for `SimpleNamespace` test stubs that don't wire
    # an affiliation.
    clinician = getattr(provider, "clinician", None)
    org_id = _role_attr(provider, "org_id")
    affiliations = list(getattr(provider, "affiliations", None) or [])
    return {
        "practice_name": (getattr(org, "name", None) if org else None),
        "practice_url": (f"/organizations/{org_id}" if org_id is not None else None),
        "full_address": full_address(
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
        "affiliations": [
            affiliation_card_view(aff, getattr(aff, "org", None))
            for aff in affiliations
        ],
    }
