"""View-projection helper shared by handlers that gate fields per viewer.

`project_view` builds a dict containing only the keys the viewer is
allowed to see. The technique — omit private keys at projection time, on
top of any template-level guard — is defense in depth: a forgotten
template `{% if %}` cannot re-leak a value the dict never contained.

The split between `public_fields` (per call) and `private_fields` (a
spec-level declaration) is deliberate: different views of the same
resource (list row vs. detail) want different *public* shapes, so
pinning a single `public_fields` to the spec would force premature
consolidation. The spec only declares *what is private*; the call site
declares *which view this is*.

`project_view` takes the privacy primitives directly (rather than a
`ResourceSpec`) so logic-layer handlers can call it without a layer-cross
through `api.routes.<entity>` — which would also be a circular import for
entities where the spec sits in the route file that imports the handler.
The spec stores the same primitives as declarative metadata for any
future cross-layer reader (JSON endpoint, audit snapshot, OpenAPI doc).
"""

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
