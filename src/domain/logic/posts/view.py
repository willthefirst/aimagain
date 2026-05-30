"""View helpers for posts — pure functions consumed by templates.

The listing row in `src/domain/templates/posts/_item.html` needs a single
4-state "insurance posture" axis to render as one icon badge. The two
kinds model the underlying data asymmetrically:

  * `referral` — `network_preference` enum
    (`in_network_required` / `in_network_preferred` / `no_preference`)
    paired with a nullable `insurance_carrier`. The posture is derived
    from `network_preference` alone — the carrier doesn't change the
    badge.
  * `opening` → linked `Clinician` — the
    `in_network_carriers` list (empty = no in-network) plus the
    `accepts_out_of_network` / `sliding_scale` booleans.

`insurance_posture_for_post(post)` collapses both shapes to a value
from `INSURANCE_POSTURES` (see `src/domain/models/enums.py`). The
ordering of branches is the priority the row should show: if a
clinician accepts in-network plans, that's the posture, even if they
also offer sliding scale — the in-network signal is louder.

`referral_headline(detail)` composes the CR card's headline
text from `age_groups[0]` + `gender`. CR posts describe one client,
so the first age group is the client's age (the schema still allows
multi for forward-compat but only the first drives the title).
Genders that don't slot in naturally — `prefer_not_to_say`,
`gender_diverse` — drop the gender word entirely.

`post_card_view(post)` is the unified view-model that both the listing
card (`_item.html`) and the detail page (`detail.html`) read from. Each
kind's underlying detail relationship has a different field set and
naming — CR holds its own (city, state, zip) location and a single
gender; PA reads location and insurance from the linked Clinician;
program reads identity from the linked Program. The function collapses
those three shapes into one flat dict so templates iterate over keys
rather than branching on `post.kind`. Values that don't apply to a
kind are ``None`` (or empty lists); templates render via
``{% if view.x %}``. Raw enum values are returned — display-label
lookup is the template's job (it's the same label dict pattern as
elsewhere).

`post_feed_headline(post)` builds the two-part headline for the
feed-row component used in the home and browse list views. Format is
``"<identity> — <clinical focus>"``: demographics + services for
referrals, practice name + services/settings for openings.

All helpers are exposed as Jinja globals by
`src/framework/rendering/templating.py`.
"""

from typing import Any

from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS_SINGULAR,
    CLIENT_AGE_GROUPS_BY_KEY,
    INSURANCE_CARRIER_LABELS,
    REFERRAL_SERVICE_LABELS,
    TREATMENT_SETTINGS_LABELS,
)
from src.framework.rendering.address import full_address

# Gender values that don't fit a "<age> <gender>" phrase. `gender_diverse`
# is the umbrella token (genderqueer / agender / two-spirit / etc.) —
# fine as a value, awkward as an adjective. `prefer_not_to_say` is the
# privacy opt-out. Both cases drop the gender word from the headline.
_GENDER_HEADLINE_WORDS: dict[str, str] = {
    "female": "female",
    "male": "male",
    "non_binary": "non-binary",
    "trans_female": "trans woman",
    "trans_male": "trans man",
}


def insurance_posture_for_post(post) -> str | None:
    """Map a `Post` (either kind) to one of `INSURANCE_POSTURES`.

    Returns `None` only when the post has no detail row (shouldn't
    happen for persisted posts, but the row template tolerates it).
    """
    kind = getattr(post, "kind", None)
    if kind == "referral":
        detail = getattr(post, "referral_detail", None)
        if detail is None:
            return None
        # Map the referrer's posture to the unified posture vocabulary.
        # The mapping mirrors the alembic migration that backfilled the
        # old `insurance` column (in_network → required, out_of_network
        # → preferred, self_pay_only → no_preference); the read path
        # inverts that to recover the original posture display.
        return {
            "in_network_required": "in_network",
            "in_network_preferred": "out_of_network",
            "no_preference": "self_pay",
        }.get(detail.network_preference)
    if kind == "clinician_opening":
        detail = getattr(post, "opening_detail", None)
        clinician = getattr(detail, "clinician", None) if detail is not None else None
        if clinician is None:
            return None
        if clinician.in_network_carriers:
            return "in_network"
        if clinician.accepts_out_of_network:
            return "out_of_network"
        if clinician.sliding_scale or clinician.cost:
            return "self_pay"
        return "please_contact"
    if kind == "program_intake":
        # Program-availability has no insurance posture today — insurance
        # is modeled on the Clinician (who delivers care) and on the
        # Client-referral Post (the referral situation), not on the
        # Program (#537 docstring on `Program`). Return None so the
        # listing row omits the chunk entirely; the detail page does
        # the same.
        return None
    return None


_KIND_VERB = {
    "referral": "Seeking",
    "clinician_opening": "Providing",
    "program_intake": "Providing",
}


def _location_chunk(
    city: str | None, state: str | None, zip_code: str | None
) -> dict | None:
    """Return ``{city, state, zip}`` when any of the three are present,
    otherwise ``None`` so templates can ``{% if view.location_chunk %}``."""
    if not any((city, state, zip_code)):
        return None
    return {"city": city, "state": state, "zip": zip_code}


def _referral_or_none(website: str | None, instructions: str | None) -> dict | None:
    """Bundle the optional PA/program "how to refer" fields. Either
    being set lights up the section; both being empty means no section."""
    if not (website or instructions):
        return None
    return {"website": website, "instructions": instructions}


# Fields copied straight off the kind's detail row with no transform, as
# `view_key -> detail_attribute`. `_forward_detail_passthrough` applies these
# for every kind before its per-kind block fills in computed/relational fields.
# A kind whose detail lacks an attribute (referral has no `settings` /
# `schedule_text` / `genders`) just keeps the base default. Adding a plain
# field to a post kind means one line here, not an edit to three per-kind
# blocks — so a passthrough field can't be silently dropped from the view-model.
_SCALAR_PASSTHROUGH: dict[str, str] = {
    "subject": "subject",
    "description": "description",
    "schedule_text": "schedule_text",
    "treatment_modality": "treatment_modality",
}
_LIST_PASSTHROUGH: dict[str, str] = {
    "services": "services",
    "settings": "settings",
    "ages": "age_groups",
    "languages": "languages",
    "genders": "genders",
    "modalities": "modalities",
    "desired_times": "desired_times",
}


def _forward_detail_passthrough(base: dict[str, Any], d: Any) -> None:
    """Copy every passthrough field off detail row ``d`` into ``base``.

    Scalars land as-is (``None`` when absent); list fields are normalized to
    a fresh list (``[]`` when absent or empty) so templates can iterate
    without nullability handling. Mutates ``base`` in place."""
    for view_key, attr in _SCALAR_PASSTHROUGH.items():
        base[view_key] = getattr(d, attr, None)
    for view_key, attr in _LIST_PASSTHROUGH.items():
        base[view_key] = list(getattr(d, attr, None) or [])


def post_card_view(post) -> dict[str, Any]:
    """Normalize a `Post` of any kind into the flat shape both the
    listing card and the detail page render from.

    Pre-pulls every field templates need so the per-kind branching
    happens here (once, in Python) instead of in three different
    templates. Missing values come back as ``None`` (scalars) or
    ``[]`` (lists) so templates render via ``{% if view.x %}`` /
    ``{% for x in view.xs %}`` without further nullability handling.

    Returns:
        kind: the discriminator (`referral` /
            `opening` / `intake`).
        kind_verb: ``"Seeking"`` for CR, ``"Providing"`` for the two
            availability kinds. Mirrors the kind-chip vocabulary the
            list card's left-edge color uses (orange = Seeking, cyan
            = Providing).
        headline: the card's identity line — CR is ``referral_headline``
            (age + gender combo); PA is the practice's org name;
            program is the program name.
        header_state: the state shown next to the headline. Program
            reads from ``program.state_preference``; CR and PA leave
            this ``None`` and surface their state via the
            demographics-column ``location_chunk`` row instead — that
            keeps the header line uncluttered and makes the two
            availability-vs-seeker kinds consistent on where location
            appears in the card.
        in_person / virtual: the post's in-person/virtual posture as
            `LOCATION_AVAILABILITY_OPTIONS` values. CR reads them off
            its own detail row; PA reads them from the linked
            Clinician's session-availability fields. Program has no
            in-person/virtual posture and returns ``None`` for both.
        services / settings: raw enum lists. PA + program carry
            ``settings``; CR's ``settings`` is empty.
        ages / languages / genders: raw enum lists. CR's single
            ``gender`` is wrapped in a list of one so templates iterate
            uniformly (a CR with ``gender = "prefer_not_to_say"``
            returns ``["prefer_not_to_say"]`` — the template still has
            the value if it wants to handle it specially).
        insurance_posture: one of ``INSURANCE_POSTURES`` or ``None``
            (intake has no posture). Same value
            ``insurance_posture_for_post`` returns.
        treatment_modality: free-text modality string or ``None``.
        location_chunk: ``{city, state, zip}`` for CR (from the
            detail row) and PA (from the linked Clinician) — the
            demographics-column icon-only row both render. ``None``
            for program (no location of its own; ``state_preference``
            still surfaces via ``header_state``).
        description: free-text description or ``None``. CR's
            description is NOT NULL on the model but the function
            stays defensive for stubs that omit it.
        schedule_text: PA/program optional schedule notes; ``None``
            for CR.
        desired_times: raw enum list of desired-time slots; empty if
            unset.
        practice_link: ``{id, name}`` of PA's linked Clinician's org;
            ``None`` for other kinds.
        program_link: ``{id, name}`` of program's linked Program;
            ``None`` for other kinds.
        organization_link: ``{id, name}`` of the post's owning
            Organization (PA reads through ``clinician.org``; program
            intake reads through ``program.organization``). ``None``
            for referral (CR has no org linkage in the model). The
            facts block renders this as a clickable link so any post
            is one click from its org's detail page.
        full_address: ``"City, ST ZIP"`` string for the detail page's
            expanded location row. CR reads from its own location;
            PA reads from the linked Clinician; program returns
            ``None``.
        sliding_scale / cost: PA-only fields from the linked Clinician;
            ``None`` for other kinds.
        network_preference / insurance_carrier: CR-only raw enum
            values from the detail row; ``None`` for other kinds.
        in_network_carriers / accepts_out_of_network: PA-only raw
            values from the linked Clinician. ``in_network_carriers``
            comes back as an empty list when unset, matching the
            list/iteration convention; ``accepts_out_of_network`` is
            ``None`` for other kinds.
        referral: ``{website, instructions}`` when either is set
            (PA/program "how to refer" section); ``None`` when both
            empty or for CR.
    """
    kind = getattr(post, "kind", None)
    base: dict[str, Any] = {
        "kind": kind,
        "kind_verb": _KIND_VERB.get(kind),
        "subject": None,
        "headline": None,
        "header_state": None,
        "in_person": None,
        "virtual": None,
        "services": [],
        "settings": [],
        "ages": [],
        "languages": [],
        "genders": [],
        "insurance_posture": insurance_posture_for_post(post),
        "treatment_modality": None,
        "modalities": [],
        "location_chunk": None,
        "description": None,
        "schedule_text": None,
        "desired_times": [],
        "practice_link": None,
        "program_link": None,
        "organization_link": None,
        "full_address": None,
        "sliding_scale": None,
        "cost": None,
        "network_preference": None,
        "insurance_carrier": None,
        "in_network_carriers": [],
        "accepts_out_of_network": None,
        "referral": None,
    }

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        base.update(
            headline=referral_headline(d),
            in_person=getattr(d, "location_in_person", None),
            virtual=getattr(d, "location_virtual", None),
            # CR holds a single `gender`; wrap it so templates iterate
            # `genders` uniformly across kinds.
            genders=([d.gender] if getattr(d, "gender", None) else []),
            location_chunk=_location_chunk(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                getattr(d, "location_zip", None),
            ),
            full_address=full_address(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                getattr(d, "location_zip", None),
            ),
            network_preference=getattr(d, "network_preference", None),
            insurance_carrier=getattr(d, "insurance_carrier", None),
        )
        return base

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        p = getattr(d, "clinician", None)
        base.update(
            headline=(p.org.name if p and getattr(p, "org", None) else None),
            # `header_state` stays None — opening's location lives in
            # the demographics column via `location_chunk` (same row
            # treatment as referral). Both kinds match on where
            # location surfaces, so the list card's header line stays
            # uncluttered for both.
            header_state=None,
            location_chunk=(
                _location_chunk(
                    getattr(p, "location_city", None),
                    getattr(p, "location_state", None),
                    getattr(p, "location_zip", None),
                )
                if p
                else None
            ),
            in_person=(getattr(p, "in_person_sessions", None) if p else None),
            virtual=(getattr(p, "virtual_sessions", None) if p else None),
            practice_link=(
                {"id": p.id, "name": p.org.name}
                if p and getattr(p, "org", None) and getattr(p, "id", None)
                else None
            ),
            organization_link=(
                {"id": p.org.id, "name": p.org.name}
                if p
                and getattr(p, "org", None)
                and getattr(p.org, "id", None)
                and getattr(p.org, "name", None)
                else None
            ),
            full_address=(
                full_address(
                    getattr(p, "location_city", None),
                    getattr(p, "location_state", None),
                    getattr(p, "location_zip", None),
                )
                if p
                else None
            ),
            sliding_scale=(getattr(p, "sliding_scale", None) if p else None),
            cost=(getattr(p, "cost", None) if p else None),
            in_network_carriers=(
                list(getattr(p, "in_network_carriers", None) or []) if p else []
            ),
            accepts_out_of_network=(
                getattr(p, "accepts_out_of_network", None) if p else None
            ),
            referral=_referral_or_none(
                getattr(d, "website", None),
                getattr(d, "referral_instructions", None),
            ),
        )
        return base

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        prog = getattr(d, "program", None)
        base.update(
            headline=(getattr(prog, "name", None) if prog else None),
            header_state=(getattr(prog, "state_preference", None) if prog else None),
            program_link=(
                {"id": prog.id, "name": prog.name}
                if prog and getattr(prog, "id", None) and getattr(prog, "name", None)
                else None
            ),
            organization_link=(
                {
                    "id": prog.organization.id,
                    "name": prog.organization.name,
                }
                if prog
                and getattr(prog, "organization", None)
                and getattr(prog.organization, "id", None)
                and getattr(prog.organization, "name", None)
                else None
            ),
            referral=_referral_or_none(
                getattr(d, "website", None),
                getattr(d, "referral_instructions", None),
            ),
        )
        return base

    return base


def referral_headline(detail) -> str:
    """Build the listing-card headline for a `referral`.

    Format: `"<Age noun> [<gender>] (<range>)"` — e.g. `"Adult male
    (25–64)"`, `"Adolescent female (14–18)"`, or `"Adult (25–64)"`
    when the gender slot is empty (`prefer_not_to_say` or
    `gender_diverse`). The age comes from `age_groups[0]` since a CR
    post describes one client; the schema still allows multi but the
    headline picks the first value.

    Returns `"Client Referral"` as a fallback when the detail has no
    age groups (defensive — schema requires min-1, so this shouldn't
    happen for persisted posts).
    """
    age_groups = getattr(detail, "age_groups", None) or []
    if not age_groups:
        return "Client Referral"
    age = CLIENT_AGE_GROUPS_BY_KEY[age_groups[0]]
    gender_word = _GENDER_HEADLINE_WORDS.get(getattr(detail, "gender", None) or "")
    if gender_word:
        return f"{age.singular} {gender_word} ({age.range})"
    return f"{age.singular} ({age.range})"


def post_row_summary(post) -> str:
    """Build the compact mid-dot summary line for the row layout.

    Used by the home-page "My active posts" widget and the list-page row
    view. Returns a " · "-joined string of the post's key facts: the
    free-text description plus the one or two most differentiating
    metadata signals (insurance carrier + city for referrals; settings +
    sliding-scale flag for openings).

    Truncates description to 100 chars so rows stay single-line on typical
    screens; metadata appended after the truncation so the separators
    always appear regardless of description length.
    """
    kind = getattr(post, "kind", None)

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return "Referral"
        parts: list[str] = []
        desc = getattr(d, "description", None)
        if desc:
            parts.append(desc[:100])
        else:
            parts.append(referral_headline(d))
        carrier = getattr(d, "insurance_carrier", None)
        if carrier:
            parts.append(INSURANCE_CARRIER_LABELS.get(carrier, carrier))
        city = getattr(d, "location_city", None)
        if city:
            parts.append(city)
        return " · ".join(parts)

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return "Opening"
        p = getattr(d, "clinician", None)
        parts = []
        desc = getattr(d, "description", None)
        if desc:
            parts.append(desc[:100])
        else:
            ages = list(getattr(d, "age_groups", None) or [])
            services = list(getattr(d, "services", None) or [])
            age_labels = [CLIENT_AGE_GROUP_LABELS_SINGULAR.get(a, a) for a in ages[:2]]
            svc_labels = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
            combined = age_labels + svc_labels
            if combined:
                parts.append(", ".join(combined))
        settings = list(getattr(d, "settings", None) or [])
        if settings:
            parts.append(TREATMENT_SETTINGS_LABELS.get(settings[0], settings[0]))
        if p and getattr(p, "sliding_scale", None):
            parts.append("sliding scale")
        return " · ".join(parts) if parts else "Opening"

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return "Program"
        prog = getattr(d, "program", None)
        name = getattr(prog, "name", None) if prog else None
        desc = getattr(d, "description", None)
        parts = []
        if name:
            parts.append(name)
        if desc:
            parts.append(desc[:80])
        return " · ".join(parts) if parts else "Program"

    return ""


def post_feed_headline(post) -> str:
    """Build the two-part feed-row headline for any post kind.

    Referrals: ``"<demographics> — <services>"``, e.g.
    ``"Adult female (25–64) — Psychotherapy, Medication management"``.
    When the referral carries no services the demographics alone are returned.

    Openings: ``"<practice name> — <clinical focus>"``, e.g.
    ``"Acme Counseling — Psychotherapy, Outpatient"``. Clinical focus
    comes from the opening's services list; settings are used as a
    fallback when services are absent. Falls back to practice name alone
    when neither is set.

    Program intakes follow the same ``"<name> — <services>"`` pattern.
    """
    kind = getattr(post, "kind", None)

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return "Referral"
        if subject := getattr(d, "subject", None):
            return subject
        demo = referral_headline(d)
        services = list(getattr(d, "services", None) or [])
        if services:
            labels = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
            return f"{demo} — {', '.join(labels)}"
        return demo

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return "Opening"
        if subject := getattr(d, "subject", None):
            return subject
        p = getattr(d, "clinician", None)
        practice = (
            p.org.name
            if p and getattr(p, "org", None) and getattr(p.org, "name", None)
            else "Opening"
        )
        services = list(getattr(d, "services", None) or [])
        focus_parts = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
        if not focus_parts:
            settings = list(getattr(d, "settings", None) or [])
            focus_parts = [TREATMENT_SETTINGS_LABELS.get(s, s) for s in settings[:2]]
        if focus_parts:
            return f"{practice} — {', '.join(focus_parts)}"
        return practice

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return "Program"
        if subject := getattr(d, "subject", None):
            return subject
        prog = getattr(d, "program", None)
        name = (getattr(prog, "name", None) if prog else None) or "Program"
        services = list(getattr(d, "services", None) or [])
        focus_parts = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
        if focus_parts:
            return f"{name} — {', '.join(focus_parts)}"
        return name

    return ""
