"""View helpers for posts — pure functions consumed by templates.

The listing row in `src/domain/templates/posts/_item.html` needs a single
4-state "insurance posture" axis to render as one icon badge. The two
kinds model the underlying data asymmetrically:

  * `client_referral` — `network_preference` enum
    (`in_network_required` / `in_network_preferred` / `no_preference`)
    paired with a nullable `insurance_carrier`. The posture is derived
    from `network_preference` alone — the carrier doesn't change the
    badge.
  * `provider_availability` → linked `Provider` — the
    `in_network_carriers` list (empty = no in-network) plus the
    `accepts_out_of_network` / `sliding_scale` booleans.

`insurance_posture_for_post(post)` collapses both shapes to a value
from `INSURANCE_POSTURES` (see `src/domain/models/enums.py`). The
ordering of branches is the priority the row should show: if a
provider accepts in-network plans, that's the posture, even if they
also offer sliding scale — the in-network signal is louder.

`client_referral_headline(detail)` composes the CR card's headline
text from `age_groups[0]` + `gender`. CR posts describe one client,
so the first age group is the client's age (the schema still allows
multi for forward-compat but only the first drives the title).
Genders that don't slot in naturally — `prefer_not_to_say`,
`gender_diverse` — drop the gender word entirely.

`post_card_view(post)` is the unified view-model that both the listing
card (`_item.html`) and the detail page (`detail.html`) read from. Each
kind's underlying detail relationship has a different field set and
naming — CR holds its own (city, state, zip) location and a single
gender; PA reads location and insurance from the linked Provider;
program reads identity from the linked Program. The function collapses
those three shapes into one flat dict so templates iterate over keys
rather than branching on `post.kind`. Values that don't apply to a
kind are ``None`` (or empty lists); templates render via
``{% if view.x %}``. Raw enum values are returned — display-label
lookup is the template's job (it's the same label dict pattern as
elsewhere).

All three helpers are exposed as Jinja globals by
`src/framework/rendering/templating.py`.
"""

from typing import Any

from src.domain.models.enums import CLIENT_AGE_GROUPS_BY_KEY

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
    if kind == "client_referral":
        detail = getattr(post, "client_referral_detail", None)
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
    if kind == "provider_availability":
        detail = getattr(post, "provider_availability_detail", None)
        if detail is None or detail.provider is None:
            return None
        provider = detail.provider
        if provider.in_network_carriers:
            return "in_network"
        if provider.accepts_out_of_network:
            return "out_of_network"
        if provider.sliding_scale or provider.cost:
            return "self_pay"
        return "please_contact"
    if kind == "program_availability":
        # Program-availability has no insurance posture today — insurance
        # is modeled on the Provider (who delivers care) and on the
        # Client-referral Post (the referral situation), not on the
        # Program (#537 docstring on `Program`). Return None so the
        # listing row omits the chunk entirely; the detail page does
        # the same.
        return None
    return None


_KIND_VERB = {
    "client_referral": "Seeking",
    "provider_availability": "Providing",
    "program_availability": "Providing",
}


def _location_chunk(
    city: str | None, state: str | None, zip_code: str | None
) -> dict | None:
    """Return ``{city, state, zip}`` when any of the three are present,
    otherwise ``None`` so templates can ``{% if view.location_chunk %}``."""
    if not any((city, state, zip_code)):
        return None
    return {"city": city, "state": state, "zip": zip_code}


def _full_address(
    city: str | None, state: str | None, zip_code: str | None
) -> str | None:
    """Compose ``"City, ST ZIP"`` for the detail page's expanded address
    row. Returns ``None`` when no parts are present so templates omit
    the row entirely."""
    if not any((city, state, zip_code)):
        return None
    head = ", ".join(p for p in (city, state) if p)
    if zip_code:
        return f"{head} {zip_code}" if head else zip_code
    return head or None


def _referral_or_none(website: str | None, instructions: str | None) -> dict | None:
    """Bundle the optional PA/program "how to refer" fields. Either
    being set lights up the section; both being empty means no section."""
    if not (website or instructions):
        return None
    return {"website": website, "instructions": instructions}


def post_card_view(post) -> dict[str, Any]:
    """Normalize a `Post` of any kind into the flat shape both the
    listing card and the detail page render from.

    Pre-pulls every field templates need so the per-kind branching
    happens here (once, in Python) instead of in three different
    templates. Missing values come back as ``None`` (scalars) or
    ``[]`` (lists) so templates render via ``{% if view.x %}`` /
    ``{% for x in view.xs %}`` without further nullability handling.

    Returns:
        kind: the discriminator (`client_referral` /
            `provider_availability` / `program_availability`).
        kind_verb: ``"Seeking"`` for CR, ``"Providing"`` for the two
            availability kinds. Mirrors the kind-chip vocabulary the
            list card's left-edge color uses (orange = Seeking, cyan
            = Providing).
        headline: the card's identity line — CR is ``client_referral_headline``
            (age + gender combo); PA is the practice's org name;
            program is the program name.
        header_state: the state shown next to the headline. PA reads
            from ``provider.location_state``; program reads from
            ``program.state_preference``; CR is ``None`` because its
            state lives in ``location_chunk`` (the demographics-column
            location row), not in the header line.
        in_person / virtual: the post's in-person/virtual posture as
            `LOCATION_AVAILABILITY_OPTIONS` values. CR reads them off
            its own detail row; PA reads them from the linked
            Provider's session-availability fields. Program has no
            in-person/virtual posture and returns ``None`` for both.
        services / settings: raw enum lists. PA + program carry
            ``settings``; CR's ``settings`` is empty.
        ages / languages / genders: raw enum lists. CR's single
            ``gender`` is wrapped in a list of one so templates iterate
            uniformly (a CR with ``gender = "prefer_not_to_say"``
            returns ``["prefer_not_to_say"]`` — the template still has
            the value if it wants to handle it specially).
        insurance_posture: one of ``INSURANCE_POSTURES`` or ``None``
            (program-availability has no posture). Same value
            ``insurance_posture_for_post`` returns.
        treatment_modality: free-text modality string or ``None``.
        location_chunk: ``{city, state, zip}`` for CR's demographics
            column; ``None`` for PA and program (PA's location is on
            the linked Provider and surfaces via ``header_state`` and
            ``full_address``; program has no location of its own).
        description: free-text description or ``None``. CR's
            description is NOT NULL on the model but the function
            stays defensive for stubs that omit it.
        schedule_text: PA/program optional schedule notes; ``None``
            for CR.
        desired_times: raw enum list of desired-time slots; empty if
            unset.
        practice_link: ``{id, name}`` of PA's linked Provider's org;
            ``None`` for other kinds.
        program_link: ``{id, name}`` of program's linked Program;
            ``None`` for other kinds.
        organization_name: program's owning organization name;
            ``None`` for other kinds.
        full_address: ``"City, ST ZIP"`` string for the detail page's
            expanded location row. CR reads from its own location;
            PA reads from the linked Provider; program returns
            ``None``.
        sliding_scale / cost: PA-only fields from the linked Provider;
            ``None`` for other kinds.
        network_preference / insurance_carrier: CR-only raw enum
            values from the detail row; ``None`` for other kinds.
        in_network_carriers / accepts_out_of_network: PA-only raw
            values from the linked Provider. ``in_network_carriers``
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
        "location_chunk": None,
        "description": None,
        "schedule_text": None,
        "desired_times": [],
        "practice_link": None,
        "program_link": None,
        "organization_name": None,
        "full_address": None,
        "sliding_scale": None,
        "cost": None,
        "network_preference": None,
        "insurance_carrier": None,
        "in_network_carriers": [],
        "accepts_out_of_network": None,
        "referral": None,
    }

    if kind == "client_referral":
        d = getattr(post, "client_referral_detail", None)
        if d is None:
            return base
        base.update(
            headline=client_referral_headline(d),
            in_person=getattr(d, "location_in_person", None),
            virtual=getattr(d, "location_virtual", None),
            services=list(getattr(d, "services", None) or []),
            ages=list(getattr(d, "age_groups", None) or []),
            languages=list(getattr(d, "languages", None) or []),
            genders=([d.gender] if getattr(d, "gender", None) else []),
            treatment_modality=getattr(d, "treatment_modality", None),
            location_chunk=_location_chunk(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                getattr(d, "location_zip", None),
            ),
            description=getattr(d, "description", None),
            desired_times=list(getattr(d, "desired_times", None) or []),
            full_address=_full_address(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                getattr(d, "location_zip", None),
            ),
            network_preference=getattr(d, "network_preference", None),
            insurance_carrier=getattr(d, "insurance_carrier", None),
        )
        return base

    if kind == "provider_availability":
        d = getattr(post, "provider_availability_detail", None)
        if d is None:
            return base
        p = getattr(d, "provider", None)
        base.update(
            headline=(p.org.name if p and getattr(p, "org", None) else None),
            header_state=(getattr(p, "location_state", None) if p else None),
            in_person=(getattr(p, "in_person_sessions", None) if p else None),
            virtual=(getattr(p, "virtual_sessions", None) if p else None),
            services=list(getattr(d, "services", None) or []),
            settings=list(getattr(d, "settings", None) or []),
            ages=list(getattr(d, "age_groups", None) or []),
            languages=list(getattr(d, "languages", None) or []),
            genders=list(getattr(d, "genders", None) or []),
            treatment_modality=getattr(d, "treatment_modality", None),
            description=getattr(d, "description", None),
            schedule_text=getattr(d, "schedule_text", None),
            desired_times=list(getattr(d, "desired_times", None) or []),
            practice_link=(
                {"id": p.id, "name": p.org.name}
                if p and getattr(p, "org", None) and getattr(p, "id", None)
                else None
            ),
            full_address=(
                _full_address(
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

    if kind == "program_availability":
        d = getattr(post, "program_availability_detail", None)
        if d is None:
            return base
        prog = getattr(d, "program", None)
        base.update(
            headline=(getattr(prog, "name", None) if prog else None),
            header_state=(getattr(prog, "state_preference", None) if prog else None),
            services=list(getattr(d, "services", None) or []),
            settings=list(getattr(d, "settings", None) or []),
            ages=list(getattr(d, "age_groups", None) or []),
            languages=list(getattr(d, "languages", None) or []),
            genders=list(getattr(d, "genders", None) or []),
            treatment_modality=getattr(d, "treatment_modality", None),
            description=getattr(d, "description", None),
            schedule_text=getattr(d, "schedule_text", None),
            desired_times=list(getattr(d, "desired_times", None) or []),
            program_link=(
                {"id": prog.id, "name": prog.name}
                if prog and getattr(prog, "id", None) and getattr(prog, "name", None)
                else None
            ),
            organization_name=(
                getattr(prog.organization, "name", None)
                if prog and getattr(prog, "organization", None)
                else None
            ),
            referral=_referral_or_none(
                getattr(d, "website", None),
                getattr(d, "referral_instructions", None),
            ),
        )
        return base

    return base


def client_referral_headline(detail) -> str:
    """Build the listing-card headline for a `client_referral`.

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
