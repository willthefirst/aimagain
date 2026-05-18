"""URL helpers for Jinja templates.

Templates should not hardcode entity URL paths. ``entity_url`` and
``entity_form_url`` compute the right path from the entity registry
(:mod:`src.framework.dispatch.registry`), so a ``url_collection``
rename — or a future grammar-shape change — is a one-place edit
rather than a 70-template grep.

Both helpers are registered as Jinja globals by
:mod:`src.framework.rendering.templating`. The lint at
``scripts/dev/template_route_check.py`` forbids hardcoded
``/<known-collection>/...`` literals in URL attributes so the helper
stays the only legal way to reach those paths from a template.

The helpers cover the **parent-resource and form-page URLs** that
the grammar prescribes (`src/domain/routes/RESOURCE_GRAMMAR.md`):

* ``entity_url(name)`` → ``/<collection>`` (list / POST-create target)
* ``entity_url(name, id=...)`` → ``/<collection>/<id>`` (detail / PATCH / DELETE)
* ``entity_form_url(name)`` → ``/<collection>/form`` (create form)
* ``entity_form_url(name, id=...)`` → ``/<collection>/<id>/form`` (edit form)

Subresource URLs (state axes, field clusters, owner-scoped lists)
stay literal in templates today — they're bespoke per resource. If a
subresource shape repeats often enough to be worth registering, add
a helper here rather than re-introducing literals.
"""

from typing import TYPE_CHECKING, Any

from src.framework.dispatch.registry import entity_registry

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


def _spec_by_name(name: str) -> "EntitySpec":
    """Look up an ``EntitySpec`` by its ``name`` (e.g. ``"organization"``).

    Raises ``ValueError`` for unknown names so a typo in a template
    fails loudly at render time rather than silently producing a path
    that 404s in the browser. The error message lists every registered
    name so the caller can correct the spelling.
    """
    for spec in entity_registry.specs():
        if spec.name == name:
            return spec
    known = sorted(s.name for s in entity_registry.specs())
    raise ValueError(
        f"Unknown entity name {name!r}. Known entities: {known}. "
        "Entity names are singular (e.g. 'organization', not 'organizations')."
    )


def _prefix(spec: "EntitySpec") -> str:
    """Compute the URL prefix for ``spec`` — mirrors the rule in
    :func:`src.framework.dispatch.base_router._make_entity_router`."""
    return (
        spec.prefix_override
        if spec.prefix_override is not None
        else f"/{spec.url_collection}"
    )


def entity_url(name: str, *, id: Any = None, subresource: str | None = None) -> str:
    """Parent-resource URL for the entity ``name``.

    ``id`` may be a ``UUID``, a string, or any value that stringifies
    cleanly — the helper does not validate the id, it just stringifies
    it into the path. ``id="me"`` is intentionally allowed so users can
    write ``entity_url("user", id="me")`` for the self-alias.

    ``subresource`` appends a single trailing path segment for state-axis
    / field-cluster subresources from the grammar (e.g.
    ``/users/{id}/activation``, ``/posts/{id}/owner-actions``). Requires
    ``id`` — a subresource without a parent id doesn't fit the grammar.
    Multi-segment subresources (``/providers/{id}/licensures/{lic_id}``)
    aren't covered by this helper; templates that need them keep the
    interpolation today, and the lint accepts them when they appear
    inside an ``entity_url(...)`` call's subresource value.
    """
    spec = _spec_by_name(name)
    prefix = _prefix(spec)
    if id is None:
        if subresource is not None:
            raise ValueError(
                "entity_url: `subresource` requires `id` — subresources "
                "without a parent id aren't in the grammar."
            )
        return prefix
    base = f"{prefix}/{id}"
    return base if subresource is None else f"{base}/{subresource}"


def entity_form_url(name: str, *, id: Any = None) -> str:
    """Form-page URL for the entity ``name``.

    Without ``id``: the create form at ``/<collection>/form``.
    With ``id``: the edit form at ``/<collection>/<id>/form``.

    Subresource form pages (``/<collection>/<id>/<sub>/form``) are
    bespoke; templates that need them keep using literal interpolation
    today. If we add a third form page for any entity, extend this
    helper rather than re-introduce literal paths.
    """
    spec = _spec_by_name(name)
    prefix = _prefix(spec)
    if id is None:
        return f"{prefix}/form"
    return f"{prefix}/{id}/form"
