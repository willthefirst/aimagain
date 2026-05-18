"""Single registry pairing every top-level `EntitySpec` with its FastAPI
router.

The route file is the unique place where a spec + its router both
exist (the file imports the spec and mounts it). Making that the
registration site means there's exactly one list — no parallel
"all specs" + "all routers" tuples drifting apart, no
filesystem-walking discovery, no `include_router(...)` line to
forget in :mod:`src.main`.

Lifecycle:

* Each entity route file under ``src/domain/routes/`` calls
  :func:`register_entity` at import time; the call constructs the
  ``BaseRouter`` (via :func:`_make_entity_router`), appends the
  ``(spec, fastapi_router)`` pair to the module-level registry, and
  returns the ``BaseRouter`` so the caller can mount handlers on it.
* ``src/domain/routes/__init__.py`` imports every entity route module —
  one explicit import per entity. Adding an entity = one line in that
  ``__init__.py``; forgetting it means the spec exists but the routes
  don't get mounted, which the conformance suite (which iterates the
  registry) flags loudly.
* :mod:`src.main` and the conformance suite iterate :data:`entity_registry`
  rather than walking filesystems or rebuilding the list.

The registry is intentionally a process-global. Specs are static
declarations; once imported, they're permanent for the lifetime of the
process. No reset hook — tests don't mutate it.
"""

from typing import TYPE_CHECKING, Final

from fastapi import APIRouter

from .base_router import BaseRouter, _make_entity_router

if TYPE_CHECKING:
    from .entity_spec import EntitySpec


class EntityRegistry:
    """Append-only registry of ``(spec, fastapi_router)`` pairs.

    Order is insertion order (Python list semantics). Consumers should
    not depend on ordering — `main.py` builds path-matching routes that
    are exact, and the conformance suite sorts by ``spec.name`` for
    readable failure output.
    """

    def __init__(self) -> None:
        self._entries: list[tuple["EntitySpec", APIRouter]] = []
        self._seen_names: set[str] = set()

    def register(self, spec: "EntitySpec", fastapi_router: APIRouter) -> None:
        """Add ``(spec, fastapi_router)`` to the registry.

        Raises ``ValueError`` if a spec with the same ``name`` is
        registered twice — the duplicate would silently double-mount
        routes and silently double the conformance suite's
        parametrization, both wrong.
        """
        if spec.name in self._seen_names:
            raise ValueError(
                f"Entity {spec.name!r} is already registered. Each spec "
                f"should be wired into exactly one route file."
            )
        self._seen_names.add(spec.name)
        self._entries.append((spec, fastapi_router))

    def entries(self) -> tuple[tuple["EntitySpec", APIRouter], ...]:
        """Snapshot of registered ``(spec, fastapi_router)`` pairs."""
        return tuple(self._entries)

    def specs(self) -> tuple["EntitySpec", ...]:
        """Just the specs, in registration order."""
        return tuple(spec for spec, _ in self._entries)


entity_registry: Final[EntityRegistry] = EntityRegistry()


def register_entity(spec: "EntitySpec") -> BaseRouter:
    """Build the spec's router and add the pair to :data:`entity_registry`.

    Replaces the old idiom of

    .. code-block:: python

        router = _make_entity_router(SPEC)
        spec_api_router = router.router

    with

    .. code-block:: python

        router = register_entity(SPEC)

    The caller still mounts handlers on ``router`` exactly as before —
    ``register_entity`` only adds the registry bookkeeping.
    """
    router = _make_entity_router(spec)
    entity_registry.register(spec, router.router)
    return router
