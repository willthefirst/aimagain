"""View projection that omits private keys at projection time: defense in depth
against a forgotten template `{% if %}` re-leaking a value the dict never contained."""

from typing import Any, Callable


def project_view(
    obj: Any,
    *,
    public_fields: tuple[str, ...],
    actor: Any,
    private_fields: tuple[str, ...] = (),
    private_field_predicate: Callable[..., bool] | None = None,
) -> dict:
    """Project `obj` into a dict of `public_fields`, optionally adding
    `private_fields` when `private_field_predicate(actor, obj)` is true.

    `private_fields` without a predicate is a misconfiguration (the
    fields would silently leak); raises `ValueError` to surface it.
    """
    if private_fields and private_field_predicate is None:
        raise ValueError(
            "project_view received private_fields without a "
            "private_field_predicate — fields would silently leak."
        )
    view: dict[str, Any] = {f: getattr(obj, f) for f in public_fields}
    if private_fields and private_field_predicate(actor, obj):
        for f in private_fields:
            view[f] = getattr(obj, f)
    return view
