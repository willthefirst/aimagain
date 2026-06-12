"""Factories that build per-spec extras callables (`detail_extras_path`,
`form_extras_path` targets) from a declarative tuple of fetches.

The hand-written extras callables are pure DI orchestration: call a
small set of repo methods, assemble a dict for the template. This
module captures that shape so a spec's hook target can be a one-line
``make_*_extras_handler(...)`` call instead of a hand-written async
def.

The hand-written form is still appropriate when the hook branches on
the requesting user (e.g. anonymous-viewer fallback, role-derived
field set) or shapes the return dict from multiple sources whose
relationship isn't 1:1 key/value. Use the factory only when each
returned key maps to one repo call.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

DetailFetch = tuple[
    str,
    str,
    Callable[[Any, Any, Any], Awaitable[Any]],
]
"""One row in the `fetches` tuple passed to `make_detail_extras_handler`.

Tuple of:

- ``context_key`` — the dict key the result lands under in the
  template context.
- ``repo_kwarg`` — the name of the typed-repo kwarg the framework
  injects (must match an entry in the spec's ``detail_extras_repos``).
- ``fetch`` — an async callable ``fetch(repo, target, requesting_user)
  -> value`` that returns the per-context-key value.

The viewer arg is always passed (even when unused) so a fetch can
react to viewer identity without changing the factory signature.
"""


def make_detail_extras_handler(
    fetches: Sequence[DetailFetch],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a ``detail_extras_path`` target from a tuple of
    ``(context_key, repo_kwarg, fetch_fn)`` fetches.

    The returned async callable matches the framework's extras contract
    (``async def hook(*, target, requesting_user, request=None,
    **typed_repos) -> dict[str, Any]``) and, for each fetch, calls
    ``fetch_fn(repos[repo_kwarg], target, requesting_user)``. Results
    assemble into a dict keyed by ``context_key`` and merge into the
    template context downstream.

    Bind the result at module top level so the spec's
    ``detail_extras_path`` can resolve it via dotted-string import.
    """
    fetches_tuple = tuple(fetches)

    async def _detail_extras(
        *,
        target: Any,
        requesting_user: Any,
        **typed_repos: Any,
    ) -> dict[str, Any]:
        return {
            key: await fetch(typed_repos[repo_kwarg], target, requesting_user)
            for key, repo_kwarg, fetch in fetches_tuple
        }

    return _detail_extras
