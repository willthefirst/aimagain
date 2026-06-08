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

# Sentinel for `entity_lock_reason(user=...)` — distinguishes
# "caller passed user=None explicitly (anonymous viewer)" from "caller
# omitted it and wants the ContextVar lookup."
_SENTINEL: Any = object()


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


def url_for_spec(spec: "EntitySpec", *, id: Any = None) -> str:
    """Spec-direct form of `entity_url` — same path resolution, no
    registry lookup.

    Used by `handle_detail` / `handle_get_new_form` / `handle_get_edit_form`
    to inject `resource_url` / `resource_detail_url` into template
    context. Routing through the spec directly lets handler tests with
    synthetic (unregistered) specs round-trip without registering them
    with `entity_registry` first.
    """
    prefix = _prefix(spec)
    if id is None:
        return prefix
    return f"{prefix}/{id}"


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
    Multi-segment subresources (``/clinicians/{id}/licensures/{lic_id}``)
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


def entity_lock_reason(name: str, user: Any = _SENTINEL) -> str | None:
    """Return the `REASON_*` code that locks links pointing at entity `name`
    for the current viewer, or `None` when the link should render normally.

    Templates use this via the `entity_link` macro
    (`_shared/_locked.html`) so any `<a>` going to a gated entity's pages
    can swap itself for a `locked_link(reason, label)` popover when the
    viewer fails the entity's `read_policy.can_read` predicate. Pure
    no-op when the spec declares no `read_policy` or no `lock_reason`.

    `user` defaults to the per-request viewer set by `set_viewer(...)`.
    Pass an explicit user from non-template callers (mount helpers that
    pre-compute breadcrumb tuples) so they don't depend on ContextVar state.

    `name=None` or a Jinja `Undefined` returns `None` — templates that
    render the chrome with partial context (chrome tests stubbing
    `views/detail.html` without injecting `entity_name`) should still
    render rather than raise.
    """
    if name is None or not isinstance(name, str):
        return None
    spec = _spec_by_name(name)
    if spec.read_policy is None or spec.read_policy.lock_reason is None:
        return None
    if user is _SENTINEL:
        from src.framework.rendering.templating import _viewer_var

        user = _viewer_var.get()
    if spec.read_policy.can_read(user):
        return None
    return spec.read_policy.lock_reason


def breadcrumb_entity_item(
    name: str,
    user: Any = _SENTINEL,
    label: str | None = None,
) -> tuple[str, str, str | None]:
    """Return the breadcrumb `(label, href, lock_reason)` tuple for the
    collection of entity `name`.

    Every view-type template's collection segment (`detail`, `form_new`,
    `form_edit`, `search`) calls this so the URL, the human label, and
    the lock-reason lookup live in one place. Adding a new view-type
    chrome that omits this call would also omit the lock affordance —
    `scripts/dev/template_route_check.py` enforces that any `<a>`
    pointing at a gated entity's collection routes through this helper
    or `entity_link(...)`.

    `label` defaults to the spec's `url_collection.capitalize()`
    (matches the original inline shape in the view-type templates).
    Override only when the page wants a different surface label (rare
    — usually the collection name reads correctly).
    """
    spec = _spec_by_name(name)
    if label is None:
        label = spec.url_collection.capitalize()
    return (
        label,
        entity_url(name),
        (
            entity_lock_reason(name)
            if user is _SENTINEL
            else entity_lock_reason(name, user)
        ),
    )


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
