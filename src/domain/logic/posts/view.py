"""View helpers for posts — pure functions consumed by templates.

The listing row in `src/domain/templates/posts/_item.html` needs a single
4-state "insurance posture" axis to render as one icon badge. The two
kinds model the underlying data asymmetrically:

  * `client_referral.insurance` — single enum
    (`in_network` / `out_of_network` / `self_pay_only` / `please_contact`).
  * `provider_availability` → linked `Provider` — boolean flags
    (`accepts_in_network`, `accepts_out_of_network`, `sliding_scale`).

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

Both helpers are exposed as Jinja globals by
`src/framework/rendering/templating.py`.
"""

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
        # `self_pay_only` storage value normalizes to the posture key
        # `self_pay`; everything else round-trips.
        return "self_pay" if detail.insurance == "self_pay_only" else detail.insurance
    if kind == "provider_availability":
        detail = getattr(post, "provider_availability_detail", None)
        if detail is None or detail.provider is None:
            return None
        provider = detail.provider
        if provider.accepts_in_network:
            return "in_network"
        if provider.accepts_out_of_network:
            return "out_of_network"
        if provider.sliding_scale or provider.cost:
            return "self_pay"
        return "please_contact"
    return None


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
