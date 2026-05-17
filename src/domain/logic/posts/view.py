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

Exposed as the `insurance_posture` Jinja global by
`src/framework/rendering/templating.py`.
"""


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
