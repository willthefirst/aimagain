"""View helpers for posts — pure functions consumed by templates.

The listing row in `src/domain/templates/posts/_item.html` needs a single
4-state "insurance posture" axis to render as one icon badge. The two
kinds model the underlying data with parallel shapes:

  * `referral` — three independent payment-path booleans
    (`accepts_in_network` / `accepts_out_of_network_superbill` /
    `accepts_private_pay`) plus an `insurance_carriers` JSON list
    of `INSURANCE_CARRIERS` tokens (#1358 PR-e). The posture is
    derived from the booleans in priority order: in-network →
    out-of-network → private-pay → please_contact (none set).
  * `opening` → linked `ClinicianAffiliation` — the
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
gender; PA reads location and insurance from the linked
ClinicianAffiliation (the practice the opening announces, NOT the
clinician's primary-affiliation proxies — a multi-affiliation
clinician's opening must show the posting practice's facts);
program reads identity from the linked Program. The function collapses
those three shapes into one flat dict so templates iterate over keys
rather than branching on `post.kind`. Values that don't apply to a
kind are ``None`` (or empty lists); templates render via
``{% if view.x %}``. Raw enum values are returned — display-label
lookup is the template's job (it's the same label dict pattern as
elsewhere).

The opening and intake branches additionally consult the linked
``ClinicianAffiliation`` (and the linked ``Clinician`` for the
person-level ``languages``) — for openings — or the linked
``Program`` — for intakes — when reading the steady-state profile
fields (`services` / `settings` / `modalities` / `age_groups` /
`genders` / `website` / `referral_instructions` / `languages`). These
fields moved off the per-announcement detail row to their steady-state
homes in #1358 PR-f; sub-3 dropped the detail-row columns, so reads
come exclusively from the new home.

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
        # Map the payment-path booleans to the unified posture vocab in
        # priority order: in-network > out-of-network > private-pay >
        # please_contact (none set). Priority matches the provider-side
        # collapse below — in-network is the loudest signal.
        if getattr(detail, "accepts_in_network", False):
            return "in_network"
        if getattr(detail, "accepts_out_of_network_superbill", False):
            return "out_of_network"
        if getattr(detail, "accepts_private_pay", False):
            return "self_pay"
        return "please_contact"
    if kind == "clinician_opening":
        detail = getattr(post, "opening_detail", None)
        affiliation = (
            getattr(detail, "clinician_affiliation", None)
            if detail is not None
            else None
        )
        if affiliation is None:
            return None
        if getattr(affiliation, "in_network_carriers", None):
            return "in_network"
        if getattr(affiliation, "accepts_out_of_network", None):
            return "out_of_network"
        if getattr(affiliation, "sliding_scale", None) or getattr(
            affiliation, "cost", None
        ):
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

# #1358 PR-f sub-3 — steady-state profile fields read exclusively from
# the new homes. The opening side reads these from the linked
# ``ClinicianAffiliation`` (and ``languages`` from the linked
# ``Clinician``); the intake side reads from the linked ``Program``.
# The detail rows no longer carry these columns at all after sub-3.
_OPENING_AFFILIATION_FIELDS: tuple[tuple[str, str], ...] = (
    # (view_key, column-on-affiliation)
    ("services", "services"),
    ("settings", "settings"),
    ("modalities", "modalities"),
    ("ages", "age_groups"),
    ("genders", "genders"),
)
_INTAKE_PROGRAM_LIST_FIELDS: tuple[tuple[str, str], ...] = (
    *_OPENING_AFFILIATION_FIELDS,
    # `languages` is person-level for openings (lives on `Clinician`) but
    # program-level for intakes — Program is the equivalent of the
    # affiliation here.
    ("languages", "languages"),
)


def _forward_detail_passthrough(base: dict[str, Any], d: Any) -> None:
    """Copy every passthrough field off detail row ``d`` into ``base``.

    Scalars land as-is (``None`` when absent); list fields are normalized to
    a fresh list (``[]`` when absent or empty) so templates can iterate
    without nullability handling. Mutates ``base`` in place."""
    for view_key, attr in _SCALAR_PASSTHROUGH.items():
        base[view_key] = getattr(d, attr, None)
    for view_key, attr in _LIST_PASSTHROUGH.items():
        base[view_key] = list(getattr(d, attr, None) or [])


def _read_list(home: Any, attr: str) -> list:
    """Steady-state list field read from the new home (affiliation /
    clinician / program). Returns a fresh list so templates can iterate
    without nullability handling. ``None`` / missing home → ``[]``."""
    return list((getattr(home, attr, None) if home is not None else None) or [])


def _read_scalar(home: Any, attr: str):
    """Steady-state scalar field read from the new home. ``None`` /
    missing home → ``None``."""
    return getattr(home, attr, None) if home is not None else None


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
            ClinicianAffiliation's session-availability fields. Program
            has no in-person/virtual posture and returns ``None`` for
            both.
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
            detail row) and PA (from the linked ClinicianAffiliation) —
            the demographics-column icon-only row both render. ``None``
            for program (no location of its own; ``state_preference``
            still surfaces via ``header_state``).
        description: free-text description or ``None``. CR's
            description is NOT NULL on the model but the function
            stays defensive for stubs that omit it.
        schedule_text: PA/program optional schedule notes; ``None``
            for CR.
        desired_times: raw enum list of desired-time slots; empty if
            unset.
        practice_link: ``{id, name}`` — the linked Clinician's id with
            the affiliation's org name; ``None`` for other kinds.
        program_link: ``{id, name}`` of program's linked Program;
            ``None`` for other kinds.
        organization_link: ``{id, name}`` of the post's owning
            Organization (PA reads through ``clinician_affiliation.org``;
            program intake reads through ``program.organization``).
            ``None`` for referral (CR has no org linkage in the model).
            The owner-context card renders this as a clickable link so
            any post is one click from its org's detail page.
        full_address: ``"City, ST ZIP"`` string for the detail page's
            expanded location row. CR reads from its own location;
            PA reads from the linked ClinicianAffiliation; program
            returns ``None``.
        accepts_in_network / accepts_out_of_network_superbill /
        accepts_private_pay: CR-only payment-path booleans from the
            detail row; ``None`` for other kinds.
        insurance_carriers: CR-only list of carrier tokens; empty list
            for CR with no carriers specified, ``[]`` for other kinds.
        affirming_identities / acceptable_license_types /
        clinical_niches: CR-only matching-dimension lists (#1358 PR-a/b/c).
            Raw token lists (free-form `str` for `clinical_niches`);
            empty list both for CR with none specified and for other
            kinds, so templates iterate uniformly via ``{% if view.x %}``.
        in_network_carriers / accepts_out_of_network / sliding_scale:
            PA-only raw values from the linked ClinicianAffiliation,
            consumed by the feed-row meta strip (``_feed_row.html``).
            ``in_network_carriers`` comes back as an empty list when
            unset; the other two are ``None`` for other kinds.

    PA ``cost`` and the "how to refer" pair (website, referral
    instructions) are NOT view-model keys — the detail page's
    owner-context card renders them straight off the linked
    ``ClinicianAffiliation`` / ``Program`` via the shared
    ``affiliation_facts`` / ``program_facts`` macros.
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
        "poster_name": None,
        "practice_link": None,
        "program_link": None,
        "organization_link": None,
        "full_address": None,
        "sliding_scale": None,
        "accepts_in_network": None,
        "accepts_out_of_network_superbill": None,
        "accepts_private_pay": None,
        "insurance_carriers": [],
        "in_network_carriers": [],
        "accepts_out_of_network": None,
        # CR-only matching-dimension lists (#1358 PR-a/b/c). Default
        # empty so the detail-page facts block can iterate them
        # uniformly across kinds via `{% if view.x %}`.
        "affirming_identities": [],
        "acceptable_license_types": [],
        "clinical_niches": [],
    }

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        _owner = getattr(post, "owner", None)
        _owner_clinicians = getattr(_owner, "clinicians", None) or []
        _rc = _owner_clinicians[0] if _owner_clinicians else None
        _fn = getattr(_rc, "first_name", None) if _rc else None
        _ln = getattr(_rc, "last_name", None) if _rc else None
        base.update(
            poster_name=" ".join(filter(None, [_fn, _ln])) or None,
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
            accepts_in_network=getattr(d, "accepts_in_network", None),
            accepts_out_of_network_superbill=getattr(
                d, "accepts_out_of_network_superbill", None
            ),
            accepts_private_pay=getattr(d, "accepts_private_pay", None),
            insurance_carriers=list(getattr(d, "insurance_carriers", None) or []),
            # CR-only matching-dimension lists (#1358 PR-a/b/c). The
            # detail-page facts block surfaces these on the expanded
            # view; empty list = "no preference / no constraint".
            affirming_identities=list(getattr(d, "affirming_identities", None) or []),
            acceptable_license_types=list(
                getattr(d, "acceptable_license_types", None) or []
            ),
            clinical_niches=list(getattr(d, "clinical_niches", None) or []),
        )
        return base

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        p = getattr(d, "clinician", None)
        # Practice-role facts (org, location, sessions) read from the
        # affiliation the opening announces — NOT through the
        # Clinician's primary-affiliation proxy properties, which would
        # show the wrong practice for a multi-affiliation clinician.
        # `languages` stays person-level on the Clinician (#1358 PR-f
        # sub-3 dropped the detail-row columns for all of these).
        affiliation = getattr(d, "clinician_affiliation", None)
        for view_key, attr in _OPENING_AFFILIATION_FIELDS:
            base[view_key] = _read_list(affiliation, attr)
        base["languages"] = _read_list(p, "languages")
        _org = _read_scalar(affiliation, "org")
        _org_name = getattr(_org, "name", None) if _org else None
        _fn = getattr(p, "first_name", None) if p else None
        _ln = getattr(p, "last_name", None) if p else None
        base.update(
            poster_name=" ".join(filter(None, [_fn, _ln])) or None,
            headline=_org_name,
            # `header_state` stays None — opening's location lives in
            # the demographics column via `location_chunk` (same row
            # treatment as referral). Both kinds match on where
            # location surfaces, so the list card's header line stays
            # uncluttered for both.
            header_state=None,
            location_chunk=_location_chunk(
                _read_scalar(affiliation, "location_city"),
                _read_scalar(affiliation, "location_state"),
                _read_scalar(affiliation, "location_zip"),
            ),
            in_person=_read_scalar(affiliation, "in_person_sessions"),
            virtual=_read_scalar(affiliation, "virtual_sessions"),
            practice_link=(
                {"id": p.id, "name": _org_name}
                if _org_name and p and getattr(p, "id", None)
                else None
            ),
            organization_link=(
                {"id": _org.id, "name": _org_name}
                if _org and getattr(_org, "id", None) and _org_name
                else None
            ),
            full_address=full_address(
                _read_scalar(affiliation, "location_city"),
                _read_scalar(affiliation, "location_state"),
                _read_scalar(affiliation, "location_zip"),
            ),
            # Feed-row meta strip (`_feed_row.html`) reads these three
            # for the opening insurance chunk.
            sliding_scale=_read_scalar(affiliation, "sliding_scale"),
            in_network_carriers=_read_list(affiliation, "in_network_carriers"),
            accepts_out_of_network=_read_scalar(affiliation, "accepts_out_of_network"),
        )
        return base

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        prog = getattr(d, "program", None)
        _prog_org = getattr(prog, "organization", None) if prog else None
        # #1358 PR-f sub-3: steady-state profile fields read exclusively
        # from the linked Program. `languages` is also Program-level on
        # this side (unlike openings, where it's person-level on the
        # Clinician).
        for view_key, attr in _INTAKE_PROGRAM_LIST_FIELDS:
            base[view_key] = _read_list(prog, attr)
        base.update(
            poster_name=(getattr(_prog_org, "name", None) if _prog_org else None),
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
    metadata signals (first insurance carrier + city for referrals;
    settings + sliding-scale flag for openings).

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
        carriers = list(getattr(d, "insurance_carriers", None) or [])
        if carriers:
            parts.append(INSURANCE_CARRIER_LABELS.get(carriers[0], carriers[0]))
        city = getattr(d, "location_city", None)
        if city:
            parts.append(city)
        return " · ".join(parts)

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return "Opening"
        affiliation = getattr(d, "clinician_affiliation", None)
        parts = []
        desc = getattr(d, "description", None)
        if desc:
            parts.append(desc[:100])
        else:
            # `age_groups` / `services` read from the linked
            # ClinicianAffiliation (#1358 PR-f).
            ages = _read_list(affiliation, "age_groups")
            services = _read_list(affiliation, "services")
            age_labels = [CLIENT_AGE_GROUP_LABELS_SINGULAR.get(a, a) for a in ages[:2]]
            svc_labels = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
            combined = age_labels + svc_labels
            if combined:
                parts.append(", ".join(combined))
        settings = _read_list(affiliation, "settings")
        if settings:
            parts.append(TREATMENT_SETTINGS_LABELS.get(settings[0], settings[0]))
        if _read_scalar(affiliation, "sliding_scale"):
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
        affiliation = getattr(d, "clinician_affiliation", None)
        _org = _read_scalar(affiliation, "org")
        practice = (getattr(_org, "name", None) if _org else None) or "Opening"
        # #1358 PR-f — services/settings read from the linked
        # ClinicianAffiliation.
        services = _read_list(affiliation, "services")
        focus_parts = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
        if not focus_parts:
            settings = _read_list(affiliation, "settings")
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
        # `services` read from the linked Program (#1358 PR-f).
        services = _read_list(prog, "services")
        focus_parts = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
        if focus_parts:
            return f"{name} — {', '.join(focus_parts)}"
        return name

    return ""
